"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { useFleetSummary } from "@/hooks/use-fleet-summary";
import { InstanceCard } from "@/components/InstanceCard";
import { EmptyState } from "@/components/EmptyState";
import { EnvFilterBar } from "@/components/EnvFilterBar";
import { FleetKpiRow } from "@/components/FleetKpiRow";
import { FleetSkeleton } from "@/components/FleetSkeleton";
import { estimateMonthlyCost } from "@/lib/cost";
import { filterByEnvironment, type EnvFilter } from "@/lib/environment";
import { CURRENCY } from "@/i18n/config";

export default function InstancesPage() {
  const t = useTranslations("Instances");
  const locale = useLocale();
  // Reaproveita o mesmo hook e o mesmo card do Painel; ganha o filtro de
  // ambiente e a linha de KPIs (via useDashboard) para ficar como no design.
  const { instances, isLoading, error } = useInstances();
  const { summary } = useDashboard();
  const { summaries } = useFleetSummary();
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const visibleInstances = useMemo(
    () => filterByEnvironment(instances, envFilter),
    [instances, envFilter]
  );
  const monthlyCost = useMemo(
    () => estimateMonthlyCost(instances, CURRENCY[locale]),
    [instances, locale]
  );

  if (isLoading) return <FleetSkeleton />;
  if (error) return <p className="text-sm text-danger">{error}</p>;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho: título + filtro de ambiente + ação de criar */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("managedCount", { count: instances.length })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <EnvFilterBar value={envFilter} onChange={setEnvFilter} size="sm" />
          <Link
            href="/instances/new"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110"
          >
            <Plus size={14} />
            {t("new")}
          </Link>
        </div>
      </div>

      <FleetKpiRow summary={summary} monthlyCost={monthlyCost} />

      {instances.length === 0 ? (
        <EmptyState
          title={t("empty.noneYet")}
          subtitle={t("empty.noneYetSub")}
          action={
            <Link
              href="/instances/new"
              className="mt-2 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110"
            >
              <Plus size={14} />
              {t("new")}
            </Link>
          }
        />
      ) : visibleInstances.length === 0 ? (
        <EmptyState
          title={t("empty.noneHere")}
          subtitle={t("empty.noneHereSub")}
        />
      ) : (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
          {visibleInstances.map((instance) => (
            <InstanceCard
              key={instance.id}
              instance={instance}
              summary={summaries.get(instance.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
