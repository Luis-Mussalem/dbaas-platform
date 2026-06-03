"use client";

import { useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { runMaintenance } from "@/lib/api";
import { useMaintenance } from "@/hooks/use-maintenance";
import type { Instance, TaskType, TaskStatus } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const BTN =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";
const BTN_GHOST =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground";

// Tarefas que rodam no banco inteiro (sem target_table). VACUUM_FULL fica de
// fora dos botões rápidos porque exige uma tabela específica (lock exclusivo).
const RUN_ACTIONS: { type: TaskType; label: string }[] = [
  { type: "vacuum", label: "VACUUM ANALYZE" },
  { type: "analyze", label: "ANALYZE" },
  { type: "reindex", label: "REINDEX" },
  { type: "kill_idle", label: "Encerrar idle" },
  { type: "kill_long", label: "Encerrar longas" },
];

const TYPE_LABEL: Record<string, string> = {
  vacuum: "VACUUM ANALYZE",
  vacuum_full: "VACUUM FULL",
  analyze: "ANALYZE",
  reindex: "REINDEX",
  kill_idle: "Encerrar idle",
  kill_long: "Encerrar longas",
};

const STATUS_CLS: Record<TaskStatus, string> = {
  completed: "text-ok border-ok/25 bg-ok/10",
  running: "text-info border-info/25 bg-info/10",
  pending: "text-info border-info/25 bg-info/10",
  failed: "text-danger border-danger/25 bg-danger/10",
};
const STATUS_LABEL: Record<TaskStatus, string> = {
  completed: "Concluído",
  running: "Em andamento",
  pending: "Pendente",
  failed: "Falhou",
};

export function MaintenanceTab({ instance }: { instance: Instance }) {
  const { tasks, isLoading, error, refresh } = useMaintenance(instance.id);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const isRunning = instance.status === "running";

  async function run(type: TaskType) {
    setBusy(type);
    setActionError(null);
    try {
      await runMaintenance(instance.id, { task_type: type });
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao executar manutenção");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ações */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Executar manutenção</h2>
          {!isRunning && <span className="text-xs text-fg-3">requer instância rodando</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          {RUN_ACTIONS.map((a) => (
            <button
              key={a.type}
              onClick={() => run(a.type)}
              disabled={!isRunning || busy !== null}
              className={BTN}
            >
              <Play size={13} /> {busy === a.type ? "Executando…" : a.label}
            </button>
          ))}
        </div>
        {actionError && (
          <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {actionError}
          </div>
        )}
      </div>

      {/* histórico */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Histórico</h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : tasks.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Nenhuma tarefa ainda.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">Tarefa</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Quando</th>
                <th className="px-4 py-2 font-medium">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs">
                    {TYPE_LABEL[t.task_type] ?? t.task_type}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                        STATUS_CLS[t.status]
                      )}
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-current" />
                      {STATUS_LABEL[t.status]}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-fg-2">
                    {timeAgo(t.started_at ?? t.scheduled_at)}
                  </td>
                  <td className="max-w-0 truncate px-4 py-2 font-mono text-xs text-fg-3">
                    {t.result_summary ?? "—"}
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
