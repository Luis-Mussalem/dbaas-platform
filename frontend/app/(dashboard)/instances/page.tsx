"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useInstances } from "@/hooks/use-instances";
import { InstanceCard } from "@/components/InstanceCard";
import { EmptyState } from "@/components/EmptyState";

export default function InstancesPage() {
  // Reaproveita o mesmo hook e o mesmo card do Painel — só muda a "moldura".
  const { instances, isLoading, error } = useInstances();

  if (isLoading) return <p className="text-sm text-fg-3">Carregando…</p>;
  if (error) return <p className="text-sm text-danger">{error}</p>;

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho com ação de criar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Instâncias</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {instances.length} banco(s) gerenciado(s)
          </p>
        </div>
        <Link
          href="/instances/new"
          className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110"
        >
          <Plus size={14} />
          Nova instância
        </Link>
      </div>

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
      ) : (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
          {instances.map((instance) => (
            <InstanceCard key={instance.id} instance={instance} />
          ))}
        </div>
      )}
    </div>
  );
}
