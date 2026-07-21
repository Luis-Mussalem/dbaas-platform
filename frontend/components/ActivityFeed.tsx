"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Activity, Cpu } from "lucide-react";
import { getAuditLogs } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { useSimulation } from "@/context/SimulationProvider";
import { actorLabel, isAuditAction, toneFor, type Tone } from "@/lib/audit";

// Cor do avatar por tom semântico. O tom vem da fonte única lib/audit.ts —
// antes era derivado aqui por substring da ação, e discordava da tela de
// Auditoria (login saía verde aqui e cinza lá).
const TONE_CLS: Record<Tone, string> = {
  ok: "text-ok bg-ok/12",
  danger: "text-danger bg-danger/12",
  warn: "text-warn bg-warn/12",
  info: "text-info bg-info/12",
  muted: "text-fg-3 bg-bg-2",
};

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function ActivityFeed() {
  const t = useTranslations("ActivityFeed");
  const tc = useTranslations("Common");
  const tAction = useTranslations("Actions.phrase");
  const { ago } = useFormatters();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  // A simulação de uso gera ações auditadas (backup, manutenção): enquanto ela
  // roda, a atividade recente se atualiza sozinha em vez de exigir F5.
  const { dataPollMs, dataVersion } = useSimulation();

  useEffect(() => {
    let active = true;

    function load() {
      getAuditLogs({ limit: 8 })
        .then((data) => active && setLogs(data))
        .catch(() => active && setLogs([]))
        .finally(() => active && setIsLoading(false));
    }

    load();
    const intervalId = setInterval(load, dataPollMs);
    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, [dataPollMs, dataVersion]);

  return (
    <div className="rounded-lg border border-border bg-surface p-3.5">
      <h2 className="mb-2 text-sm font-semibold">{t("title")}</h2>

      {isLoading ? (
        <p className="py-4 text-center text-xs text-fg-3">{tc("loading")}</p>
      ) : logs.length === 0 ? (
        <p className="py-4 text-center text-xs text-fg-3">{t("empty")}</p>
      ) : (
        <ul className="flex flex-col">
          {logs.map((log) => {
            const isSystem = !log.user_id;
            // Nome real do ator (nome@empresa); cai em "operator" se o usuário
            // foi deletado (user_id presente, mas sem email no join).
            const actor = isSystem ? t("system") : actorLabel(log.user_email) ?? t("operator");
            return (
              <li
                key={log.id}
                className="flex items-center gap-2.5 border-b border-border py-2 last:border-0"
              >
                <div
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                    TONE_CLS[toneFor(log.action)]
                  }`}
                >
                  {isSystem ? <Cpu size={13} /> : <Activity size={13} />}
                </div>
                <p className="flex-1 text-[12.5px] leading-snug text-fg-2">
                  <span className="font-medium text-foreground">{actor}</span>{" "}
                  {/* Ação desconhecida (backend novo) → mostra a chave crua. */}
                  {isAuditAction(log.action) ? tAction(log.action) : log.action}
                  {log.resource_id && (
                    <span className="font-mono text-foreground"> {shortId(log.resource_id)}</span>
                  )}
                </p>
                <span className="shrink-0 font-mono text-[11px] text-fg-3">
                  {ago(log.timestamp)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
