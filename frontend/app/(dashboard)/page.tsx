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
import { periodForHour, type Period } from "@/lib/greeting";
import { filterByEnvironment, type EnvFilter } from "@/lib/environment";
import { CURRENCY } from "@/i18n/config";

// O período nunca muda durante a sessão — nada a que assinar.
const subscribeToNothing = () => () => {};

export default function PainelPage() {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  // O Painel compõe TRÊS fontes de dados reais:
  //  - useDashboard(): agregados de GET /admin/dashboard
  //  - useInstances(): lista de instâncias
  //  - ActivityFeed:  audit log (busca própria, dentro do componente)
  // Tudo se refresca sozinho a cada DASHBOARD_POLL_MS — a frota tem vida-base
  // contínua, então há sempre algo novo a mostrar.
  const { instances, isLoading: loadingInstances } = useInstances(DASHBOARD_POLL_MS);
  const { summary, isLoading: loadingSummary } = useDashboard(DASHBOARD_POLL_MS);
  // Agregado por instância (alertas, backup, uptime, throughput) para os cards,
  // numa requisição só em vez de quatro por card.
  const { summaries } = useFleetSummary(DASHBOARD_POLL_MS);
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const isLoading = loadingInstances || loadingSummary;

  // Filtro por ambiente (client-side, sobre o campo real instance.environment).
  const visibleInstances = useMemo(
    () => filterByEnvironment(instances, envFilter),
    [instances, envFilter]
  );

  // Moeda segue o idioma: tabelas de preço independentes (ver lib/cost.ts).
  const monthlyCost = useMemo(
    () => estimateMonthlyCost(instances, CURRENCY[locale]),
    [instances, locale]
  );

  // O período depende do relógio do usuário, que o servidor não conhece: lê-lo
  // no render (ou num inicializador lazy) divergiria na hidratação se os fusos
  // diferissem. useSyncExternalStore entrega `null` como snapshot de servidor e
  // troca pelo valor real após hidratar — sem mismatch e sem setState em effect.
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
      {/* cabeçalho: saudação + resumo + filtro de ambiente */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {/* Sem período ainda (primeiro paint) → só a saudação neutra. */}
            {t("greeting", { period: period ?? "other" })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("summaryAlerts", { count: alerts })} {t("summaryBackups", { count: backups })}
          </p>
        </div>
        <EnvFilterBar value={envFilter} onChange={setEnvFilter} size="sm" />
      </div>

      {/* KPIs de performance da frota (queries/s, p95, gasto, uptime) */}
      <FleetKpiRow summary={summary} monthlyCost={monthlyCost} />

      {/* 2 colunas: bancos (esq) + mapa de regiões e atividade (dir) */}
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
