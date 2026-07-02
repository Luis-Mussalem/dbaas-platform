"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useInstances } from "@/hooks/use-instances";
import { useDashboard } from "@/hooks/use-dashboard";
import { InstanceCard } from "@/components/InstanceCard";
import { EmptyState } from "@/components/EmptyState";
import { EnvFilterBar } from "@/components/EnvFilterBar";
import { FleetKpiRow } from "@/components/FleetKpiRow";
import { estimateMonthlyCost } from "@/lib/cost";
import { filterByEnvironment, type EnvFilter } from "@/lib/environment";

export default function InstancesPage() {
  // Reaproveita o mesmo hook e o mesmo card do Painel; ganha o filtro de
  // ambiente e a linha de KPIs (via useDashboard) para ficar como no design.
  const { instances, isLoading, error } = useInstances();
  const { summary } = useDashboard();
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");

  const visibleInstances = useMemo(
    () => filterByEnvironment(instances, envFilter),
    [instances, envFilter]
  );
  const monthlyCost = useMemo(() => estimateMonthlyCost(instances), [instances]);

  if (isLoading) return <p className="text-sm text-fg-3">Carregando…</p>;
  if (error) return <p className="text-sm text-danger">{error}</p>;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho: título + filtro de ambiente + ação de criar */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Instâncias</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {instances.length} banco(s) gerenciado(s)
          </p>
        </div>
        <div className="flex items-center gap-3">
          <EnvFilterBar value={envFilter} onChange={setEnvFilter} size="sm" />
          <Link
            href="/instances/new"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110"
          >
            <Plus size={14} />
            Nova instância
          </Link>
        </div>
      </div>

      <FleetKpiRow summary={summary} monthlyCost={monthlyCost} />

      {instances.length === 0 ? (
        <EmptyState
          title="Nenhuma instância ainda"
          subtitle="Crie sua primeira instância para começar a gerenciar."
          action={
            <Link
              href="/instances/new"
              className="mt-2 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110"
            >
              <Plus size={14} />
              Nova instância
            </Link>
          }
        />
      ) : visibleInstances.length === 0 ? (
        <EmptyState
          title="Nenhum banco neste ambiente"
          subtitle="Tente outro filtro de ambiente."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
          {visibleInstances.map((instance) => (
            <InstanceCard key={instance.id} instance={instance} />
          ))}
        </div>
      )}
    </div>
  );
}
