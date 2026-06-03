"use client";

import { useState } from "react";
import { ScrollText } from "lucide-react";
import { useAudit } from "@/hooks/use-audit";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const INPUT =
  "h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground outline-none transition focus:border-brand";
const BTN =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

// Metadados de cada ação: rótulo legível + "tom" (cor do badge). Espelha a
// tabela _AUDIT_ACTIONS do middleware (backend/src/core/audit_middleware.py).
type Tone = "ok" | "info" | "warn" | "danger" | "muted";

const ACTION_META: Record<string, { label: string; tone: Tone }> = {
  register: { label: "Conta registrada", tone: "info" },
  login: { label: "Login", tone: "muted" },
  logout: { label: "Logout", tone: "muted" },
  instance_created: { label: "Instância criada", tone: "ok" },
  instance_status_changed: { label: "Status alterado", tone: "info" },
  instance_deleted: { label: "Instância removida", tone: "danger" },
  backup_created: { label: "Backup criado", tone: "ok" },
  restore_initiated: { label: "Restore iniciado", tone: "warn" },
  schedule_created: { label: "Agendamento criado", tone: "ok" },
  schedule_deleted: { label: "Agendamento removido", tone: "danger" },
  maintenance_run: { label: "Manutenção executada", tone: "info" },
};

const RESOURCE_LABELS: Record<string, string> = {
  user: "Usuário",
  auth: "Autenticação",
  instance: "Instância",
  backup: "Backup",
  backup_schedule: "Agendamento",
  maintenance: "Manutenção",
};

const TONE_CLS: Record<Tone, string> = {
  ok: "text-ok border-ok/25 bg-ok/10",
  info: "text-info border-info/25 bg-info/10",
  warn: "text-warn border-warn/25 bg-warn/10",
  danger: "text-danger border-danger/25 bg-danger/10",
  muted: "text-fg-2 border-border bg-surface-2",
};

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export default function AuditPage() {
  // Estado dos filtros vive AQUI (na página) e é passado ao hook como
  // parâmetro. Trocar um <select> re-renderiza a página → o hook recebe novos
  // filtros → o effect reseta para a página 0. "" significa "sem filtro".
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");

  const { logs, isLoading, error, hasMore, loadMore } = useAudit({
    action: action || undefined,
    resource_type: resourceType || undefined,
  });

  return (
    <div className="flex flex-col gap-4">
      {/* cabeçalho */}
      <div className="flex items-center gap-2">
        <ScrollText size={20} className="text-fg-2" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Logs &amp; Auditoria</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Trilha de ações registradas na plataforma.
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* barra de filtros */}
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">Ação</span>
            <select value={action} onChange={(e) => setAction(e.target.value)} className={INPUT}>
              <option value="">Todas</option>
              {Object.keys(ACTION_META).map((a) => (
                <option key={a} value={a}>
                  {ACTION_META[a].label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">Recurso</span>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className={INPUT}
            >
              <option value="">Todos</option>
              {Object.keys(RESOURCE_LABELS).map((r) => (
                <option key={r} value={r}>
                  {RESOURCE_LABELS[r]}
                </option>
              ))}
            </select>
          </label>
        </div>

        {/* tabela */}
        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : logs.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">
            Nenhum registro para os filtros atuais.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">Ação</th>
                <th className="px-4 py-2 font-medium">Recurso</th>
                <th className="px-4 py-2 font-medium">IP</th>
                <th className="px-4 py-2 font-medium">Quando</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                const meta = ACTION_META[log.action];
                return (
                  <tr key={log.id} className="border-t border-border">
                    <td className="px-4 py-2">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          TONE_CLS[meta?.tone ?? "muted"]
                        )}
                      >
                        {meta?.label ?? log.action}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-fg-2">
                      {RESOURCE_LABELS[log.resource_type] ?? log.resource_type}
                      {log.resource_id && (
                        <span className="ml-1.5 font-mono text-xs text-fg-3">
                          {shortId(log.resource_id)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-fg-3">
                      {log.ip_address ?? "—"}
                    </td>
                    <td
                      className="px-4 py-2 text-fg-2"
                      title={new Date(log.timestamp).toLocaleString("pt-BR")}
                    >
                      {timeAgo(log.timestamp)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* paginação */}
        {hasMore && !isLoading && (
          <div className="border-t border-border px-4 py-3 text-center">
            <button onClick={loadMore} className={BTN}>
              Carregar mais
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
