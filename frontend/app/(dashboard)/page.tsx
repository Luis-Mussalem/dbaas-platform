"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { useFleetSummary } from "@/hooks/use-fleet-summary";
import { DASHBOARD_POLL_MS } from "@/lib/constants";
import { InstanceCard } from "@/components/InstanceCard";
import { ActivityFeed } from "@/components/ActivityFeed";
import { RegionMap } from "@/components/RegionMap";
import { EmptyState } from "@/components/EmptyState";
import { EnvFilterBar } from "@/components/EnvFilterBar";
import { FleetKpiRow } from "@/components/FleetKpiRow";
import { FleetSkeleton } from "@/components/FleetSkeleton";
import { estimateMonthlyCost } from "@/lib/cost";
import { qpsScaleMax } from "@/lib/qps-scale";
import { periodForHour, type Period } from "@/lib/greeting";
import { filterByEnvironment, type EnvFilter } from "@/lib/environment";
import { CURRENCY } from "@/i18n/config";

// The period never changes during the session — nothing to subscribe to.
const subscribeToNothing = () => () => {};

export default function PainelPage() {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  // The Dashboard composes THREE real data sources:
  //  - useDashboard(): aggregates from GET /admin/dashboard
  //  - useInstances(): the instance list
  //  - ActivityFeed:  audit log (its own fetch, inside the component)
  // Everything refreshes itself every DASHBOARD_POLL_MS — the fleet has a continuous
  // baseline of activity, so there's always something new to show.
  const { instances, isLoading: loadingInstances } = useInstances(DASHBOARD_POLL_MS);
  const { summary, isLoading: loadingSummary } = useDashboard(DASHBOARD_POLL_MS);
  // Per-instance aggregate (alerts, backup, uptime, throughput) for the cards,
  // in a single request instead of four per card.
  const { summaries } = useFleetSummary(DASHBOARD_POLL_MS);
  // Common (zero-based) ceiling for the queries/s sparklines: a scale shared across
  // the cards, so the line's height encodes magnitude and not just shape.
  const qpsScale = useMemo(
    () => qpsScaleMax([...summaries.values()].map((s) => s.queries_per_second)),
    [summaries],
  );
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const isLoading = loadingInstances || loadingSummary;

  // Environment filter (client-side, over the real instance.environment field).
  const visibleInstances = useMemo(
    () => filterByEnvironment(instances, envFilter),
    [instances, envFilter]
  );

  // Currency follows the language: independent price tables (see lib/cost.ts).
  const monthlyCost = useMemo(
    () => estimateMonthlyCost(instances, CURRENCY[locale]),
    [instances, locale]
  );

  // The period depends on the user's clock, which the server doesn't know: reading it
  // during render (or in a lazy initializer) would diverge at hydration if the timezones
  // differed. useSyncExternalStore delivers `null` as the server snapshot and
  // swaps in the real value after hydration — no mismatch, no setState in an effect.
  const period = useSyncExternalStore<Period | null>(
    subscribeToNothing,
    () => periodForHour(new Date().getHours()),
    () => null
  );

  if (isLoading) {
    return <FleetSkeleton />;
  }

  const alerts = summary?.active_alerts ?? 0;
  const backups = summary?.backups_last_24h ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* header: greeting + summary + environment filter */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {/* No period yet (first paint) → just the neutral greeting. */}
            {t("greeting", { period: period ?? "other" })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("summaryAlerts", { count: alerts })} {t("summaryBackups", { count: backups })}
          </p>
        </div>
        <EnvFilterBar value={envFilter} onChange={setEnvFilter} size="sm" />
      </div>

      {/* Fleet performance KPIs (queries/s, p95, cost, uptime) */}
      <FleetKpiRow summary={summary} monthlyCost={monthlyCost} />

      {/* 2 columns: databases (left) + region map and activity (right) */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">{t("yourDatabases")}</h2>
            <span className="text-xs text-fg-3">
              {t("instanceCount", { count: visibleInstances.length })}
            </span>
          </div>

          {visibleInstances.length === 0 ? (
            <EmptyState
              title={envFilter === "all" ? t("empty.noneYet") : t("empty.noneHere")}
              subtitle={envFilter === "all" ? t("empty.noneYetSub") : t("empty.noneHereSub")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
              {visibleInstances.map((instance) => (
                <InstanceCard
                  key={instance.id}
                  instance={instance}
                  summary={summaries.get(instance.id)}
                  qpsScaleMax={qpsScale}
                />
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <RegionMap instances={instances} />
          <ActivityFeed />
        </div>
      </div>
    </div>
  );
}
