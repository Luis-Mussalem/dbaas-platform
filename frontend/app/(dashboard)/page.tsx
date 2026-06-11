"use client";

import { useMemo, useState } from "react";
import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { StatCard } from "@/components/StatCard";
import { InstanceCard } from "@/components/InstanceCard";
import { ActivityFeed } from "@/components/ActivityFeed";
import { RegionMap } from "@/components/RegionMap";
import { EmptyState } from "@/components/EmptyState";
import { Segmented } from "@/components/Segmented";
import { formatBRL } from "@/lib/format";
import type { Environment, Instance } from "@/lib/types";

// Estimativa de custo mensal a partir das specs (derivado, NÃO faturamento real).
// Tarifas ilustrativas em BRL/mês — apenas para dar concretude ao card "Gasto".
function estimateMonthlyCost(instances: Instance[]): number {
  const PER_VCPU = 60;
  const PER_GB_RAM = 20;
  const PER_GB_STORAGE = 1.5;
  return instances.reduce((sum, i) => {
    const cpu = (i.cpu ?? 0) * PER_VCPU;
    const ram = ((i.memory_mb ?? 0) / 1024) * PER_GB_RAM;
    const disk = (i.storage_gb ?? 0) * PER_GB_STORAGE;
    return sum + cpu + ram + disk;
  }, 0);
}

type EnvFilter = "all" | Environment;

const ENV_FILTERS: { value: EnvFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "production", label: "produção" },
  { value: "staging", label: "homologação" },
  { value: "development", label: "desenvolvimento" },
];

export default function PainelPage() {
  // O Painel compõe TRÊS fontes de dados reais:
  //  - useDashboard(): agregados de GET /admin/dashboard
  //  - useInstances(): lista de instâncias
  //  - ActivityFeed:  audit log (busca própria, dentro do componente)
  const { instances, isLoading: loadingInstances } = useInstances();
  const { summary, isLoading: loadingSummary } = useDashboard();
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const isLoading = loadingInstances || loadingSummary;

  // Saudação por horário do dia.
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";

  // Filtro por ambiente (client-side, sobre o campo real instance.environment).
  const visibleInstances = useMemo(
    () =>
      envFilter === "all"
        ? instances
        : instances.filter((i) => i.environment === envFilter),
    [instances, envFilter]
  );

  const monthlyCost = useMemo(() => estimateMonthlyCost(instances), [instances]);

  if (isLoading) {
    return <p className="text-sm text-fg-3">Carregando…</p>;
  }

  const running = summary?.instances_by_status?.running ?? 0;
  const alerts = summary?.active_alerts ?? 0;
  const backups = summary?.backups_last_24h ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho: saudação + resumo + filtro de ambiente */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Olá, {greeting.toLowerCase()} ✦</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {alerts === 0
              ? "Seus bancos estão saudáveis."
              : `${alerts} alerta(s) ativo(s) requer(em) atenção.`}{" "}
            {backups} backup(s) nas últimas 24h.
          </p>
        </div>
        <Segmented options={ENV_FILTERS} value={envFilter} onChange={setEnvFilter} size="sm" />
      </div>

      {/* KPIs: três reais (instâncias, alertas, backups) + um derivado (gasto) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Instâncias"
          value={summary?.total_instances ?? 0}
          sub={`${running} rodando`}
          accent="ok"
        />
        <StatCard
          label="Alertas ativos"
          value={alerts}
          sub={alerts ? "requer atenção" : "tudo tranquilo"}
          accent={alerts ? "danger" : "ok"}
        />
        <StatCard
          label="Backups (24h)"
          value={backups}
          sub={
            summary?.failed_backups_last_24h
              ? `${summary.failed_backups_last_24h} falharam`
              : "sem falhas"
          }
          accent={summary?.failed_backups_last_24h ? "warn" : "default"}
        />
        <StatCard
          label="Gasto mensal"
          value={formatBRL(monthlyCost)}
          sub="estimativa por specs"
        />
      </div>

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
