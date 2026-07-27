"use client";

import { useTranslations } from "next-intl";
import { StatCard } from "@/components/StatCard";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { useFormatters } from "@/hooks/use-formatters";
import type { DashboardSummary } from "@/lib/types";

// Fleet performance KPI row (Dashboard + Instances).
// The count of instances/alerts/backups lives in the greeting and in the list's
// header — here go the performance and cost metrics, as in the design.
// P95 Latency and Uptime show "—" while there isn't yet enough real data
// (never a fabricated zero).
export function FleetKpiRow({
  summary,
  monthlyCost,
}: {
  summary: DashboardSummary | null;
  monthlyCost: number;
}) {
  const t = useTranslations("Dashboard.kpi");
  const tc = useTranslations("Common");
  const { number, cost, ratio } = useFormatters();
  const qps = summary?.queries_per_second ?? 0;
  const p95 = summary?.p95_latency_ms;
  const uptime = summary?.fleet_uptime_pct;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        label={t("qps")}
        value={<AnimatedNumber value={qps} format={(n) => number(n)} />}
        sub={t("qpsSub")}
      />
      <StatCard
        label={t("p95")}
        value={p95 != null ? `${number(p95)} ms` : tc("none")}
        sub={t("p95Sub")}
      />
      <StatCard label={t("spend")} value={cost(monthlyCost)} sub={t("spendSub")} />
      <StatCard
        label={t("uptime")}
        value={uptime != null ? `${ratio(uptime, 2)}%` : tc("none")}
        sub={uptime != null ? t("uptimeSub") : t("uptimeCollecting")}
        accent={uptime != null ? (uptime < 99 ? "warn" : "ok") : "default"}
      />
    </div>
  );
}
