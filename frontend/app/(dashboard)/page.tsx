"use client";

import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { StatCard } from "@/components/StatCard";
import { InstanceCard } from "@/components/InstanceCard";
import { ActivityFeed } from "@/components/ActivityFeed";
import { EmptyState } from "@/components/EmptyState";

export default function PainelPage() {
  // O Painel compõe TRÊS fontes de dados reais:
  //  - useDashboard(): agregados de GET /admin/dashboard
  //  - useInstances(): lista de instâncias
  //  - ActivityFeed:  audit log (busca própria, dentro do componente)
  const { instances, isLoading: loadingInstances } = useInstances();
  const { summary, isLoading: loadingSummary } = useDashboard();

  const isLoading = loadingInstances || loadingSummary;

  // Saudação por horário do dia.
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";

  if (isLoading) {
    return <p className="text-sm text-fg-3">Carregando…</p>;
  }

  const running = summary?.instances_by_status?.running ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{greeting} ✦</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {summary
            ? `${summary.total_instances} instância(s) · ${running} rodando · ${summary.backups_last_24h} backup(s) nas últimas 24h`
            : "Visão geral da plataforma."}
        </p>
      </div>

      {/* KPIs reais (os de Queries/s, Latência, Gasto e Uptime do design
          voltam quando houver métricas-como-taxa e billing) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Instâncias"
          value={summary?.total_instances ?? 0}
          sub={`${running} rodando`}
          accent="ok"
        />
        <StatCard
          label="Alertas ativos"
          value={summary?.active_alerts ?? 0}
          sub={summary?.active_alerts ? "requer atenção" : "tudo tranquilo"}
          accent={summary?.active_alerts ? "danger" : "ok"}
        />
        <StatCard
          label="Backups (24h)"
          value={summary?.backups_last_24h ?? 0}
          sub={
            summary?.failed_backups_last_24h
              ? `${summary.failed_backups_last_24h} falharam`
              : "sem falhas"
          }
          accent={summary?.failed_backups_last_24h ? "warn" : "default"}
        />
        <StatCard
          label="Manutenção pendente"
          value={summary?.pending_maintenance_tasks ?? 0}
          sub="tarefas na fila"
        />
      </div>

      {/* 2 colunas: bancos (esq) + atividade (dir) */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Seus bancos</h2>
            <span className="text-xs text-fg-3">{instances.length} instância(s)</span>
          </div>

          {instances.length === 0 ? (
            <EmptyState
              title="Nenhum banco ainda"
              subtitle="Crie sua primeira instância para começar a monitorar."
            />
          ) : (
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
              {instances.map((instance) => (
                <InstanceCard key={instance.id} instance={instance} />
              ))}
            </div>
          )}
        </div>

        <ActivityFeed />
      </div>
    </div>
  );
}
