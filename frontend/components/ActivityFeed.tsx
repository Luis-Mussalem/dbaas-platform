"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Activity, Cpu } from "lucide-react";
import { getAuditLogs } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { DASHBOARD_POLL_MS } from "@/lib/constants";
import { actorLabel, isAuditAction, toneFor, type Tone } from "@/lib/audit";

// Avatar color by semantic tone. The tone comes from the single source lib/audit.ts —
// it used to be derived here by substring-matching the action, and disagreed with the
// Audit screen (login came out green here and gray there).
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

  useEffect(() => {
    let active = true;

    function load() {
      getAuditLogs({ limit: 8 })
        .then((data) => active && setLogs(data))
        .catch(() => active && setLogs([]))
        .finally(() => active && setIsLoading(false));
    }

    load();
    const intervalId = setInterval(load, DASHBOARD_POLL_MS);
    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, []);

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
            // Actor's real name (name@company); falls back to "operator" if the user
            // was deleted (user_id present, but no email from the join).
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
                  {/* Unknown action (new backend) → shows the raw key. */}
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
