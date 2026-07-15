"use client";

import { useState } from "react";
import { ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAudit } from "@/hooks/use-audit";
import { useFormatters } from "@/hooks/use-formatters";
import {
  AUDIT_ACTIONS,
  RESOURCE_TYPES,
  isAuditAction,
  isResourceType,
  toneFor,
  type Tone,
} from "@/lib/audit";
import { cn } from "@/lib/utils";
import { BTN, INPUT } from "@/lib/ui";

// Cor do badge por tom semântico. O tom e a lista de ações vêm da fonte única
// lib/audit.ts; os rótulos, das mensagens (Actions.label.*).
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
  const t = useTranslations("Audit");
  const tc = useTranslations("Common");
  const tAction = useTranslations("Actions.label");
  const { ago, dateTime } = useFormatters();
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
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* barra de filtros */}
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">
              {t("filters.action")}
            </span>
            <select value={action} onChange={(e) => setAction(e.target.value)} className={INPUT}>
              <option value="">{t("filters.allActions")}</option>
              {AUDIT_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {tAction(a)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">
              {t("filters.resource")}
            </span>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className={INPUT}
            >
              <option value="">{t("filters.allResources")}</option>
              {RESOURCE_TYPES.map((r) => (
                <option key={r} value={r}>
                  {t(`resources.${r}`)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {/* tabela */}
        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : logs.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">{t("columns.action")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.resource")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.ip")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.when")}</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                return (
                  <tr key={log.id} className="border-t border-border">
                    <td className="px-4 py-2">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          TONE_CLS[toneFor(log.action)]
                        )}
                      >
                        {/* Ação/recurso desconhecidos (backend novo, frontend
                            antigo) → mostra a chave crua em vez de quebrar. */}
                        {isAuditAction(log.action) ? tAction(log.action) : log.action}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-fg-2">
                      {isResourceType(log.resource_type)
                        ? t(`resources.${log.resource_type}`)
                        : log.resource_type}
                      {log.resource_id && (
                        <span className="ml-1.5 font-mono text-xs text-fg-3">
                          {shortId(log.resource_id)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-fg-3">
                      {log.ip_address ?? tc("none")}
                    </td>
                    <td
                      className="px-4 py-2 text-fg-2"
                      title={dateTime(log.timestamp, "full")}
                    >
                      {ago(log.timestamp)}
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
              {t("loadMore")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
