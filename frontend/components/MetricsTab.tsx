"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getMetricHistory } from "@/lib/api";
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

// Série de latência DEMO (p50/p95/p99) — sintética, claramente rotulada.
// O backend ainda não coleta latência por query; isto ilustra o gráfico.
function demoLatency(n: number, hhmm: (iso: string) => string): ChartPoint[] {
  const base = Date.now() - n * 60_000;
  return Array.from({ length: n }, (_, i) => {
    const wob = Math.sin(i / 4) * 3;
    return {
      t: hhmm(new Date(base + i * 60_000).toISOString()),
      p50: Math.round(8 + wob + (i % 3)),
      p95: Math.round(18 + wob * 1.5 + (i % 4)),
      p99: Math.round(31 + wob * 2 + (i % 5)),
    };
  });
}

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
  const [conns, setConns] = useState<ChartPoint[]>([]);
  const [cache, setCache] = useState<ChartPoint[]>([]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getMetricHistory(instance.id, "connections_active", range),
      getMetricHistory(instance.id, "cache_hit_ratio", range),
    ])
      .then(([c, h]) => {
        if (!active) return;
        setConns(c.points.map((p) => ({ t: hhmm(p.collected_at), v: Math.round(p.value) })));
        setCache(h.points.map((p) => ({ t: hhmm(p.collected_at), v: Number(p.value.toFixed(2)) })));
      })
      .catch(() => {
        if (active) {
          setConns([]);
          setCache([]);
        }
      });
    return () => {
      active = false;
    };
  }, [instance.id, range, hhmm]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <Segmented options={WINDOWS} value={range} onChange={setRange} size="sm" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title={t("connections")} tag="real">
          {conns.length > 1 ? (
            <MetricArea data={conns} color="#34d399" />
          ) : (
            <Empty />
          )}
        </ChartCard>

        <ChartCard title={t("cacheHit")} tag="real">
          {cache.length > 1 ? (
            <MetricArea data={cache} color="#60a5fa" />
          ) : (
            <Empty />
          )}
        </ChartCard>
      </div>

      <ChartCard title={t("latency")} tag="demo">
        <MultiLineChart
          data={demoLatency(40, hhmm)}
          series={[
            { key: "p50", color: "#34d399" },
            { key: "p95", color: "#60a5fa" },
            { key: "p99", color: "#fbbf24" },
          ]}
        />
      </ChartCard>
    </div>
  );
}

function ChartCard({
  title,
  tag,
  children,
}: {
  title: string;
  // "demo" marca a série sintética de latência — o rótulo exibido é traduzido,
  // mas a distinção real/demo é do dado, não do idioma.
  tag: "real" | "demo";
  children: React.ReactNode;
}) {
  const t = useTranslations("Metrics.tag");
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold">{title}</h3>
        <span
          className={`rounded-full border px-1.5 py-0.5 text-[10px] ${
            tag === "real"
              ? "border-ok/25 bg-ok/10 text-ok"
              : "border-border text-fg-3"
          }`}
        >
          {t(tag)}
        </span>
      </div>
      {children}
    </div>
  );
}

function Empty() {
  const t = useTranslations("Metrics");
  return <p className="py-14 text-center text-sm text-fg-3">{t("emptySeries")}</p>;
}
