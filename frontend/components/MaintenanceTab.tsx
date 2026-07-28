"use client";

import { useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { runMaintenance } from "@/lib/api";
import { useMaintenance } from "@/hooks/use-maintenance";
import { useToast } from "@/context/ToastProvider";
import type { Instance, TaskType, TaskStatus } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { cn } from "@/lib/utils";
import { useCanManage } from "@/hooks/use-permissions";
import { BTN, BTN_GHOST } from "@/lib/ui";

// Tasks that run on the entire database (no target_table). VACUUM_FULL is left
// out of the quick buttons because it requires a specific table (exclusive lock).
const RUN_ACTIONS: TaskType[] = ["vacuum", "analyze", "reindex", "kill_idle", "kill_long"];

const STATUS_CLS: Record<TaskStatus, string> = {
  completed: "text-ok border-ok/25 bg-ok/10",
  running: "text-info border-info/25 bg-info/10",
  pending: "text-info border-info/25 bg-info/10",
  failed: "text-danger border-danger/25 bg-danger/10",
};
export function MaintenanceTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Maintenance");
  const tc = useTranslations("Common");
  const canManage = useCanManage();
  const { ago } = useFormatters();
  const { tasks, isLoading, error, refresh } = useMaintenance(instance.id);
  const [busy, setBusy] = useState<string | null>(null);
  const { toast } = useToast();

  const isRunning = instance.status === "running";

  async function run(type: TaskType) {
    setBusy(type);
    try {
      await runMaintenance(instance.id, { task_type: type });
      await refresh();
      toast.success(t("toast.ran", { type }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.runFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* actions */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">{t("runTitle")}</h2>
          {!isRunning && <span className="text-xs text-fg-3">{tc("requiresRunning")}</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          {/* VACUUM/REINDEX take locks on live tables — admins only. */}
          {canManage ? (
            RUN_ACTIONS.map((type) => (
              <button
                key={type}
                onClick={() => run(type)}
                disabled={!isRunning || busy !== null}
                className={BTN}
              >
                <Play size={13} /> {busy === type ? t("running") : t(`tasks.${type}`)}
              </button>
            ))
          ) : (
            <span className="text-xs text-fg-3">{tc("readOnlyRole")}</span>
          )}
        </div>
      </div>

      {/* history */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t("historyTitle")}</h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> {tc("refresh")}
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : tasks.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">{t("columns.task")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.status")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.when")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.result")}</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs">{t(`tasks.${task.task_type}`)}</td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                        STATUS_CLS[task.status]
                      )}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-current" />
                      {t(`status.${task.status}`)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-fg-2">
                    {ago(task.started_at ?? task.scheduled_at)}
                  </td>
                  {/* result_summary comes raw from the backend (English) — translating it would require
                      structured codes in the API. It's kept under a translated label. */}
                  <td className="max-w-0 truncate px-4 py-2 font-mono text-xs text-fg-3">
                    {task.result_summary ?? tc("none")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
