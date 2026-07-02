"use client";

import { useMemo, useState } from "react";
import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { InstanceCard } from "@/components/InstanceCard";
import { ActivityFeed } from "@/components/ActivityFeed";
import { RegionMap } from "@/components/RegionMap";
import { EmptyState } from "@/components/EmptyState";
import { EnvFilterBar } from "@/components/EnvFilterBar";
import { FleetKpiRow } from "@/components/FleetKpiRow";
import { estimateMonthlyCost } from "@/lib/cost";
import { greetingForHour } from "@/lib/greeting";
import { filterByEnvironment, type EnvFilter } from "@/lib/environment";

export default function PainelPage() {
  // O Painel compõe TRÊS fontes de dados reais:
  //  - useDashboard(): agregados de GET /admin/dashboard
  //  - useInstances(): lista de instâncias
  //  - ActivityFeed:  audit log (busca própria, dentro do componente)
  const { instances, isLoading: loadingInstances } = useInstances();
  const { summary, isLoading: loadingSummary } = useDashboard();
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const isLoading = loadingInstances || loadingSummary;

  // Filtro por ambiente (client-side, sobre o campo real instance.environment).
  const visibleInstances = useMemo(
    () => filterByEnvironment(instances, envFilter),
    [instances, envFilter]
  );

  const monthlyCost = useMemo(() => estimateMonthlyCost(instances), [instances]);

  if (isLoading) {
    return <p className="text-sm text-fg-3">Carregando…</p>;
  }

  const alerts = summary?.active_alerts ?? 0;
  const backups = summary?.backups_last_24h ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho: saudação + resumo + filtro de ambiente */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Olá, {greetingForHour().toLowerCase()} ✦
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {alerts === 0
              ? "Seus bancos estão saudáveis."
              : `${alerts} alerta(s) ativo(s) requer(em) atenção.`}{" "}
            {backups} backup(s) nas últimas 24h.
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
            <h2 className="text-sm font-semibold">Seus bancos</h2>
            <span className="text-xs text-fg-3">{visibleInstances.length} instância(s)</span>
          </div>

          {visibleInstances.length === 0 ? (
            <EmptyState
              title={envFilter === "all" ? "Nenhum banco ainda" : "Nenhum banco neste ambiente"}
              subtitle={
                envFilter === "all"
                  ? "Crie sua primeira instância para começar a monitorar."
                  : "Tente outro filtro de ambiente."
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
              {visibleInstances.map((instance) => (
                <InstanceCard key={instance.id} instance={instance} />
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
