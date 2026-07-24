"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getMetricHistory } from "@/lib/api";
import { DASHBOARD_POLL_MS } from "@/lib/constants";
import type { Instance, MetricWindow } from "@/lib/types";
import { Segmented } from "@/components/Segmented";
import { MetricArea, MultiLineChart, type ChartPoint } from "@/components/MetricChart";

// Janelas de tempo: os rótulos são unidades técnicas, iguais nos dois idiomas.
const WINDOWS: { value: MetricWindow; label: string }[] = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
];

// Percentis de latência exibidos, na ordem em que se empilham no gráfico.
const LATENCY_SERIES = [
  { key: "p50", metric: "p50_query_latency_ms", color: "#34d399" },
  { key: "p95", metric: "p95_query_latency_ms", color: "#60a5fa" },
  { key: "p99", metric: "p99_query_latency_ms", color: "#fbbf24" },
] as const;

export function MetricsTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Metrics");
  const locale = useLocale();
  // Intl preso ao locale, e não o useFormatters: o hhmm roda DENTRO do effect
  // de busca, e o objeto do useFormatters muda a cada 60s (useNow) — isso
  // refaria o fetch das séries a cada minuto. Aqui só muda ao trocar de idioma.
  const timeFormat = useMemo(
    () => new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }),
    [locale]
  );
  const hhmm = useCallback((iso: string) => timeFormat.format(new Date(iso)), [timeFormat]);

  const [range, setRange] = useState<MetricWindow>("1h");
  const [throughput, setThroughput] = useState<ChartPoint[]>([]);
  const [conns, setConns] = useState<ChartPoint[]>([]);
  const [cache, setCache] = useState<ChartPoint[]>([]);
  const [latency, setLatency] = useState<ChartPoint[]>([]);
  // Estes gráficos buscavam UMA vez e nunca mais — a página mais "de
  // monitoramento" do produto era a única que exigia F5 para mostrar dado novo.
  // Agora se refrescam a cada DASHBOARD_POLL_MS.
  useEffect(() => {
    let active = true;

    function load() {
      Promise.all([
        getMetricHistory(instance.id, "queries_per_second", range),
        getMetricHistory(instance.id, "connections_active", range),
        getMetricHistory(instance.id, "cache_hit_ratio", range),
        ...LATENCY_SERIES.map((s) => getMetricHistory(instance.id, s.metric, range)),
      ])
        .then(([q, c, h, ...percentiles]) => {
          if (!active) return;
          setThroughput(q.points.map((p) => ({ t: hhmm(p.collected_at), v: Number(p.value.toFixed(1)) })));
          setConns(c.points.map((p) => ({ t: hhmm(p.collected_at), v: Math.round(p.value) })));
          setCache(h.points.map((p) => ({ t: hhmm(p.collected_at), v: Number(p.value.toFixed(2)) })));
          // As três séries vêm em requisições separadas mas compartilham os
          // instantes de coleta (o poller grava todas no mesmo collected_at),
          // então dá para casá-las por índice num único conjunto de pontos.
          setLatency(
            percentiles[0].points.map((point, i) => {
              const row: ChartPoint = { t: hhmm(point.collected_at) };
              LATENCY_SERIES.forEach((s, k) => {
                const value = percentiles[k].points[i]?.value;
                if (value != null) row[s.key] = Number(value.toFixed(2));
              });
              return row;
            })
          );
        })
        .catch(() => {
          if (active) {
            setThroughput([]);
            setConns([]);
            setCache([]);
            setLatency([]);
          }
        });
    }

    load();
    const intervalId = setInterval(load, DASHBOARD_POLL_MS);
    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, [instance.id, range, hhmm]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <Segmented options={WINDOWS} value={range} onChange={setRange} size="sm" />
      </div>

      {/* queries/s em destaque: é a grandeza-título do card da frota. */}
      <ChartCard title={t("throughput")}>
        {throughput.length > 1 ? (
          <MetricArea data={throughput} color="#a78bfa" />
        ) : (
          <Empty />
        )}
      </ChartCard>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title={t("connections")}>
          {conns.length > 1 ? (
            <MetricArea data={conns} color="#34d399" />
          ) : (
            <Empty />
          )}
        </ChartCard>

        <ChartCard title={t("cacheHit")}>
          {cache.length > 1 ? (
            <MetricArea data={cache} color="#60a5fa" />
          ) : (
            <Empty />
          )}
        </ChartCard>
      </div>

      <ChartCard title={t("latency")}>
        {latency.length > 1 ? (
          <MultiLineChart
            data={latency}
            series={LATENCY_SERIES.map(({ key, color }) => ({ key, color }))}
          />
        ) : (
          <Empty />
        )}
      </ChartCard>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  // O badge "real"/"demo" existia para separar estes gráficos da série de
  // latência fabricada. Agora TODA série aqui é medida, e um selo "real" em
  // três de três não distingue nada — só ocupa espaço.
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <h3 className="mb-2 text-[13px] font-semibold">{title}</h3>
      {children}
    </div>
  );
}

function Empty() {
  const t = useTranslations("Metrics");
  return <p className="py-14 text-center text-sm text-fg-3">{t("emptySeries")}</p>;
}
