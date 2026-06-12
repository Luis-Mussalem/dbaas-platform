"use client";

import { useState } from "react";
import { Save, Download, RefreshCw } from "lucide-react";
import { createBackup, restoreBackup } from "@/lib/api";
import { useBackups } from "@/hooks/use-backups";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type { Backup, BackupStatus, BackupStrategy, Instance } from "@/lib/types";
import { formatBytes, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const BTN_SM =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";
const BTN_GHOST =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

const STATUS_CLS: Record<BackupStatus, string> = {
  completed: "text-ok border-ok/25 bg-ok/10",
  running: "text-info border-info/25 bg-info/10",
  pending: "text-info border-info/25 bg-info/10",
  failed: "text-danger border-danger/25 bg-danger/10",
  deleted: "text-fg-3 border-border bg-bg-2",
};
const STATUS_LABEL: Record<BackupStatus, string> = {
  completed: "Concluído",
  running: "Em andamento",
  pending: "Pendente",
  failed: "Falhou",
  deleted: "Removido",
};

export function BackupsTab({ instance }: { instance: Instance }) {
  const { backups, isLoading, error, refresh } = useBackups(instance.id);
  // `busy` guarda qual ação está em andamento: "logical", "physical" ou o id do backup em restore.
  const [busy, setBusy] = useState<string | null>(null);
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const isRunning = instance.status === "running";

  async function handleCreate(strategy: BackupStrategy) {
    setBusy(strategy);
    try {
      await createBackup(instance.id, strategy);
      await refresh();
      toast.success(`Backup ${strategy === "logical" ? "lógico" : "físico"} criado.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Falha ao criar backup");
    } finally {
      setBusy(null);
    }
  }

  async function handleRestore(backup: Backup) {
    const ok = await confirm({
      title: "Restaurar este backup?",
      description:
        "Os dados atuais do banco serão substituídos. Esta ação é destrutiva.",
      confirmText: "Restaurar",
      danger: true,
    });
    if (!ok) return;
    setBusy(backup.id);
    try {
      await restoreBackup(backup.id);
      toast.success("Restauração iniciada.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Falha ao restaurar");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      {/* cabeçalho + ações */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Backups</h2>
        <div className="flex items-center gap-2">
          <button onClick={refresh} className={BTN_SM}>
            <RefreshCw size={13} /> Atualizar
          </button>
          <button
            onClick={() => handleCreate("logical")}
            disabled={!isRunning || busy !== null}
            className={BTN_SM}
          >
            <Save size={13} /> {busy === "logical" ? "Criando…" : "Backup lógico"}
          </button>
          <button
            onClick={() => handleCreate("physical")}
            disabled={!isRunning || busy !== null}
            className={BTN_SM}
          >
            <Save size={13} /> {busy === "physical" ? "Criando…" : "Backup físico"}
          </button>
        </div>
      </div>

      {!isRunning && (
        <div className="border-b border-border bg-bg-2 px-4 py-2 text-xs text-fg-3">
          A instância precisa estar <span className="text-foreground">rodando</span> para
          criar ou restaurar backups.
        </div>
      )}
      {error && (
        <div className="border-b border-border bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {/* tabela */}
      {isLoading ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
      ) : backups.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Nenhum backup ainda.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">Tipo</th>
              <th className="px-4 py-2 font-medium">Criado</th>
              <th className="px-4 py-2 font-medium">Tamanho</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {backups.map((b) => (
              <tr key={b.id} className="border-t border-border">
                <td className="px-4 py-2">
                  <span className="font-mono text-xs">
                    {b.strategy === "logical" ? "lógico" : "físico"}
                  </span>
                  <span className="ml-2 text-[11px] text-fg-3">
                    {b.backup_type === "manual" ? "manual" : "agendado"}
                  </span>
                </td>
                <td className="px-4 py-2 text-fg-2">{timeAgo(b.created_at)}</td>
                <td className="px-4 py-2 font-mono text-fg-2">{formatBytes(b.size_bytes)}</td>
                <td className="px-4 py-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                      STATUS_CLS[b.status]
                    )}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                    {STATUS_LABEL[b.status]}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  {b.strategy === "logical" && b.status === "completed" && (
                    <button
                      onClick={() => handleRestore(b)}
                      disabled={!isRunning || busy !== null}
                      className={BTN_GHOST}
                    >
                      <Download size={13} /> {busy === b.id ? "Restaurando…" : "Restaurar"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
