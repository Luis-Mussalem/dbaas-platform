"use client";

import { useState } from "react";
import { Save, Download, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { createBackup, restoreBackup } from "@/lib/api";
import { useBackups } from "@/hooks/use-backups";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type { Backup, BackupStatus, BackupStrategy, Instance } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST } from "@/lib/ui";

const STATUS_CLS: Record<BackupStatus, string> = {
  completed: "text-ok border-ok/25 bg-ok/10",
  running: "text-info border-info/25 bg-info/10",
  pending: "text-info border-info/25 bg-info/10",
  failed: "text-danger border-danger/25 bg-danger/10",
  deleted: "text-fg-3 border-border bg-bg-2",
};
export function BackupsTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Backups");
  const tc = useTranslations("Common");
  const { ago, bytes } = useFormatters();
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
      toast.success(t("toast.created", { strategy }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.createFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function handleRestore(backup: Backup) {
    const ok = await confirm({
      title: t("restore.title"),
      description: t("restore.description"),
      confirmText: t("restore.action"),
      danger: true,
    });
    if (!ok) return;
    setBusy(backup.id);
    try {
      await restoreBackup(backup.id);
      toast.success(t("toast.restoreStarted"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.restoreFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      {/* cabeçalho + ações */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <div className="flex items-center gap-2">
          <button onClick={refresh} className={BTN}>
            <RefreshCw size={13} /> {tc("refresh")}
          </button>
          <button
            onClick={() => handleCreate("logical")}
            disabled={!isRunning || busy !== null}
            className={BTN}
          >
            <Save size={13} /> {busy === "logical" ? tc("creating") : t("newLogical")}
          </button>
          <button
            onClick={() => handleCreate("physical")}
            disabled={!isRunning || busy !== null}
            className={BTN}
          >
            <Save size={13} /> {busy === "physical" ? tc("creating") : t("newPhysical")}
          </button>
        </div>
      </div>

      {!isRunning && (
        <div className="border-b border-border bg-bg-2 px-4 py-2 text-xs text-fg-3">
          {t.rich("needsRunning", {
            b: (chunks) => <span className="text-foreground">{chunks}</span>,
          })}
        </div>
      )}
      {error && (
        <div className="border-b border-border bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {/* tabela */}
      {isLoading ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
      ) : backups.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">{t("columns.type")}</th>
              <th className="px-4 py-2 font-medium">{t("columns.created")}</th>
              <th className="px-4 py-2 font-medium">{t("columns.size")}</th>
              <th className="px-4 py-2 font-medium">{t("columns.status")}</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {backups.map((b) => (
              <tr key={b.id} className="border-t border-border">
                <td className="px-4 py-2">
                  <span className="font-mono text-xs">{t(`strategy.${b.strategy}`)}</span>
                  <span className="ml-2 text-[11px] text-fg-3">
                    {b.backup_type === "manual" ? t("type.manual") : t("type.scheduled")}
                  </span>
                </td>
                <td className="px-4 py-2 text-fg-2">{ago(b.created_at)}</td>
                <td className="px-4 py-2 font-mono text-fg-2">{bytes(b.size_bytes)}</td>
                <td className="px-4 py-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                      STATUS_CLS[b.status]
                    )}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                    {t(`status.${b.status}`)}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  {b.strategy === "logical" && b.status === "completed" && (
                    <button
                      onClick={() => handleRestore(b)}
                      disabled={!isRunning || busy !== null}
                      className={BTN_GHOST}
                    >
                      <Download size={13} /> {busy === b.id ? t("restoring") : t("restore.action")}
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
