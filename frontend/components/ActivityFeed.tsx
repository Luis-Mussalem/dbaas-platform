"use client";

import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { getAuditLogs } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import { timeAgo } from "@/lib/format";

// Traduz a "action" técnica do audit log para uma frase legível em PT.
// (No design isso era texto mock; aqui vem do GET /admin/audit-log real.)
const ACTION_LABELS: Record<string, string> = {
  register: "registrou uma conta",
  login: "entrou na plataforma",
  logout: "saiu da plataforma",
  instance_created: "criou a instância",
  instance_status_changed: "alterou o status de",
  instance_deleted: "removeu a instância",
  backup_created: "criou um backup de",
  restore_initiated: "iniciou um restore de",
  schedule_created: "criou um agendamento em",
  schedule_deleted: "removeu um agendamento de",
  maintenance_run: "rodou manutenção em",
};

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function ActivityFeed() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getAuditLogs({ limit: 8 })
      .then(setLogs)
      .catch(() => setLogs([]))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <div className="rounded-lg border border-border bg-surface p-3.5">
      <h2 className="mb-2 text-sm font-semibold">Atividade recente</h2>

      {isLoading ? (
        <p className="py-4 text-center text-xs text-fg-3">Carregando…</p>
      ) : logs.length === 0 ? (
        <p className="py-4 text-center text-xs text-fg-3">Nenhuma atividade ainda.</p>
      ) : (
        <ul className="flex flex-col">
          {logs.map((log) => (
            <li
              key={log.id}
              className="flex items-center gap-3 border-b border-border py-2 last:border-0"
            >
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-bg-2 text-fg-3">
                <Activity size={13} />
              </div>
              <p className="flex-1 text-[12.5px] leading-snug text-fg-2">
                {ACTION_LABELS[log.action] ?? log.action}
                {log.resource_id && (
                  <span className="font-mono text-foreground"> {shortId(log.resource_id)}</span>
                )}
              </p>
              <span className="shrink-0 font-mono text-[11px] text-fg-3">
                {timeAgo(log.timestamp)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
