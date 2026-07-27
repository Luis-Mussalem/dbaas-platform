"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { getMetricHistory } from "@/lib/api";
import { DASHBOARD_POLL_MS } from "@/lib/constants";
import type { Instance, MetricWindow } from "@/lib/types";
import { Segmented } from "@/components/Segmented";
import { MetricArea, MultiLineChart, type ChartPoint } from "@/components/MetricChart";

// Time windows: the labels are technical units, the same in both languages.
const WINDOWS: { value: MetricWindow; label: string }[] = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
];

// Latency percentiles shown, in the order they stack in the chart.
const LATENCY_SERIES = [
  { key: "p50", metric: "p50_query_latency_ms", color: "#34d399" },
  { key: "p95", metric: "p95_query_latency_ms", color: "#60a5fa" },
  { key: "p99", metric: "p99_query_latency_ms", color: "#fbbf24" },
] as const;

export function MetricsTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Metrics");
  const locale = useLocale();
  // Intl pinned to the locale, not useFormatters: hhmm runs INSIDE the fetch
  // effect, and the useFormatters object changes every 60s (useNow) — that
  // would redo the series fetch every minute. Here it only changes when the language changes.
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
  // These charts used to fetch ONCE and never again — the product's most
  // "monitoring"-like page was the only one that required an F5 to show new data.
  // Now they refresh every DASHBOARD_POLL_MS.
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
          // The three series come from separate requests but share the
          // collection instants (the poller writes all of them at the same collected_at),
          // so they can be matched by index into a single set of points.
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

      {/* queries/s featured: it's the fleet card's headline quantity. */}
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
  // The "real"/"demo" badge used to exist to separate these charts from the
  // fabricated latency series. Now EVERY series here is measured, and a "real" tag on
  // three out of three distinguishes nothing — it just takes up space.
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
