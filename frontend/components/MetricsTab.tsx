"use client";

import { useEffect, useState } from "react";
import { getMetricHistory } from "@/lib/api";
import type { Instance, MetricWindow } from "@/lib/types";
import { Segmented } from "@/components/Segmented";
import { MetricArea, MultiLineChart, type ChartPoint } from "@/components/MetricChart";

const WINDOWS: { value: MetricWindow; label: string }[] = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
];

function hhmm(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

// Série de latência DEMO (p50/p95/p99) — sintética, claramente rotulada.
// O backend ainda não coleta latência por query; isto ilustra o gráfico.
function demoLatency(n: number): ChartPoint[] {
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
  }, [instance.id, range]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Métricas</h2>
        <Segmented options={WINDOWS} value={range} onChange={setRange} size="sm" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title="Conexões ativas" tag="real">
          {conns.length > 1 ? (
            <MetricArea data={conns} color="#34d399" />
          ) : (
            <Empty />
          )}
        </ChartCard>

        <ChartCard title="Cache hit ratio (%)" tag="real">
          {cache.length > 1 ? (
            <MetricArea data={cache} color="#60a5fa" />
          ) : (
            <Empty />
          )}
        </ChartCard>
      </div>

      <ChartCard title="Latência (p50 / p95 / p99)" tag="demonstração">
        <MultiLineChart
          data={demoLatency(40)}
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
  tag: "real" | "demonstração";
  children: React.ReactNode;
}) {
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
          {tag}
        </span>
      </div>
      {children}
    </div>
  );
}

function Empty() {
  return (
    <p className="py-14 text-center text-sm text-fg-3">
      Sem série suficiente nesta janela.
    </p>
  );
}
