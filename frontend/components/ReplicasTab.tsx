"use client";

import { useState } from "react";
import { GitBranch, RefreshCw, ArrowUpCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { createReplica, promoteReplica } from "@/lib/api";
import { useReplicas } from "@/hooks/use-replicas";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type { Instance, ReplicationState } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST } from "@/lib/ui";

// Cores semânticas por estado de replicação (mesmo vocabulário visual dos outros
// badges). Espelha o enum ReplicationState do backend; os rótulos vêm do i18n.
const STATE_CLS: Record<ReplicationState, string> = {
  pending: "text-info border-info/25 bg-info/10",
  provisioning: "text-info border-info/25 bg-info/10",
  streaming: "text-ok border-ok/25 bg-ok/10",
  catchup: "text-warn border-warn/25 bg-warn/10",
  disconnected: "text-danger border-danger/25 bg-danger/10",
  promoted: "text-fg-3 border-border bg-bg-2",
  failed: "text-danger border-danger/25 bg-danger/10",
};

export function ReplicasTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Replicas");
  const tc = useTranslations("Common");
  const { ago, bytes, ratio } = useFormatters();

  // Lag em segundos → string curta. null (sem medição ainda) vira "—".
  // Vive no componente porque o decimal passa pelo Intl do locale ativo.
  function lagSeconds(seconds: number | null): string {
    if (seconds == null) return tc("none");
    if (seconds < 1) return "< 1 s";
    return `${ratio(seconds, 1)} s`;
  }
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
      toast.success(t("toast.created"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.createFailed"));
    } finally {
      setCreating(false);
    }
  }

  async function handlePromote(replicaId: string) {
    const ok = await confirm({
      title: t("promote.title"),
      description: t("promote.description"),
      confirmText: t("promote.action"),
      danger: true,
    });
    if (!ok) return;
    setPromoting(replicaId);
    try {
      await promoteReplica(replicaId);
      await refresh();
      toast.success(t("toast.promoted"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.promoteFailed"));
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
            <h2 className="text-sm font-semibold">{t("title")}</h2>
            <p className="mt-0.5 text-xs text-fg-3">{t("subtitle")}</p>
          </div>
          {!isRunning && <span className="text-xs text-fg-3">{tc("requiresRunning")}</span>}
        </div>
        <button
          onClick={handleCreate}
          disabled={!isRunning || creating}
          className={BTN}
        >
          <GitBranch size={13} /> {creating ? t("creating") : t("create")}
        </button>
      </div>

      {/* lista de réplicas */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t("listTitle")}</h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> {tc("refresh")}
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : replicas.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">{t("columns.standby")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.state")}</th>
                <th className="px-4 py-2 text-right font-medium">{t("columns.lagBytes")}</th>
                <th className="px-4 py-2 text-right font-medium">{t("columns.lagTime")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.created")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {replicas.map((r) => {
                const isPromoted = r.replication_state === "promoted";
                return (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-4 py-2 font-mono text-xs text-foreground">
                      {r.replica_instance?.name ?? tc("none")}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          STATE_CLS[r.replication_state]
                        )}
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-current" />
                        {t(`state.${r.replication_state}`)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-fg-2">
                      {bytes(r.lag_bytes)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-fg-2">
                      {lagSeconds(r.lag_seconds)}
                    </td>
                    <td className="px-4 py-2 text-fg-2">{ago(r.created_at)}</td>
                    <td className="px-4 py-2">
                      <button
                        className={BTN_GHOST}
                        disabled={isPromoted || promoting === r.id}
                        title={isPromoted ? t("promote.already") : t("promote.tooltip")}
                        onClick={() => handlePromote(r.id)}
                      >
                        <ArrowUpCircle size={13} />
                        {promoting === r.id ? t("promoting") : t("promote.action")}
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
