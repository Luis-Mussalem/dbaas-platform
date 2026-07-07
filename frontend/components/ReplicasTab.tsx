"use client";

import { useState } from "react";
import { GitBranch, RefreshCw, ArrowUpCircle } from "lucide-react";
import { createReplica, promoteReplica } from "@/lib/api";
import { useReplicas } from "@/hooks/use-replicas";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type { Instance, ReplicationState } from "@/lib/types";
import { formatBytes, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST } from "@/lib/ui";

// Estado de replicação → rótulo PT + cores semânticas (mesmo vocabulário visual
// dos outros badges). Espelha o enum ReplicationState do backend.
const STATE_META: Record<ReplicationState, { label: string; cls: string }> = {
  pending: { label: "Pendente", cls: "text-info border-info/25 bg-info/10" },
  provisioning: { label: "Provisionando", cls: "text-info border-info/25 bg-info/10" },
  streaming: { label: "Streaming", cls: "text-ok border-ok/25 bg-ok/10" },
  catchup: { label: "Alcançando", cls: "text-warn border-warn/25 bg-warn/10" },
  disconnected: { label: "Desconectado", cls: "text-danger border-danger/25 bg-danger/10" },
  promoted: { label: "Promovido", cls: "text-fg-3 border-border bg-bg-2" },
  failed: { label: "Falhou", cls: "text-danger border-danger/25 bg-danger/10" },
};

// Lag em segundos → string curta. null (sem medição ainda) vira "—".
function formatLagSeconds(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 1) return "< 1 s";
  return `${seconds.toFixed(1)} s`;
}

export function ReplicasTab({ instance }: { instance: Instance }) {
  const { replicas, isLoading, error, refresh } = useReplicas(instance.id);
  const [creating, setCreating] = useState(false);
  const [promoting, setPromoting] = useState<string | null>(null);
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const isRunning = instance.status === "running";

  async function handleCreate() {
    setCreating(true);
    try {
      await createReplica(instance.id);
      await refresh();
      toast.success("Réplica criada e replicando.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Falha ao criar réplica");
    } finally {
      setCreating(false);
    }
  }

  async function handlePromote(replicaId: string) {
    const ok = await confirm({
      title: "Promover esta réplica a primário?",
      description:
        "O standby deixa de replicar e passa a aceitar escritas como um primário " +
        "independente. Failover manual — não há como desfazer automaticamente.",
      confirmText: "Promover",
      danger: true,
    });
    if (!ok) return;
    setPromoting(replicaId);
    try {
      await promoteReplica(replicaId);
      await refresh();
      toast.success("Réplica promovida a primário.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Falha ao promover réplica");
    } finally {
      setPromoting(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ação: criar réplica */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">Replicação em streaming</h2>
            <p className="mt-0.5 text-xs text-fg-3">
              Um standby recebe o WAL do primário em tempo real (hot standby, read-only).
            </p>
          </div>
          {!isRunning && <span className="text-xs text-fg-3">requer instância rodando</span>}
        </div>
        <button
          onClick={handleCreate}
          disabled={!isRunning || creating}
          className={BTN}
        >
          <GitBranch size={13} /> {creating ? "Criando réplica…" : "Criar réplica"}
        </button>
      </div>

      {/* lista de réplicas */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Réplicas</h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : replicas.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">
            Nenhuma réplica ainda.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">Standby</th>
                <th className="px-4 py-2 font-medium">Estado</th>
                <th className="px-4 py-2 text-right font-medium">Lag (bytes)</th>
                <th className="px-4 py-2 text-right font-medium">Lag (tempo)</th>
                <th className="px-4 py-2 font-medium">Criada</th>
                <th className="px-4 py-2 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody>
              {replicas.map((r) => {
                const meta = STATE_META[r.replication_state] ?? STATE_META.pending;
                const isPromoted = r.replication_state === "promoted";
                return (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-4 py-2 font-mono text-xs text-foreground">
                      {r.replica_instance?.name ?? "—"}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          meta.cls
                        )}
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-current" />
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-fg-2">
                      {formatBytes(r.lag_bytes)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-fg-2">
                      {formatLagSeconds(r.lag_seconds)}
                    </td>
                    <td className="px-4 py-2 text-fg-2">{timeAgo(r.created_at)}</td>
                    <td className="px-4 py-2">
                      <button
                        className={BTN_GHOST}
                        disabled={isPromoted || promoting === r.id}
                        title={isPromoted ? "Já promovida" : "Promover a primário"}
                        onClick={() => handlePromote(r.id)}
                      >
                        <ArrowUpCircle size={13} />
                        {promoting === r.id ? "Promovendo…" : "Promover"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
