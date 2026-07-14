"use client";

import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import { useLogs } from "@/hooks/use-logs";
import type { Instance } from "@/lib/types";
import { BTN_GHOST } from "@/lib/ui";

export function LogsTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Logs");
  const tc = useTranslations("Common");
  const td = useTranslations("InstanceDetail");
  const { logs, isLoading, error, refresh } = useLogs(instance.id);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">{t("title")}</h2>
          <p className="mt-0.5 text-xs text-fg-3">{t("subtitle")}</p>
        </div>
        <button onClick={refresh} className={BTN_GHOST}>
          <RefreshCw size={13} /> {td("refresh")}
        </button>
      </div>

      {isLoading ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
      ) : error ? (
        <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
      ) : !logs || !logs.trim() ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
      ) : (
        // pre com scroll próprio: logs largos rolam sem quebrar o layout da página.
        <pre className="max-h-[28rem] overflow-auto px-4 py-3 font-mono text-xs leading-relaxed text-fg-2">
          {logs}
        </pre>
      )}
    </div>
  );
}
