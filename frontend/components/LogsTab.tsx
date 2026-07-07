"use client";

import { RefreshCw } from "lucide-react";
import { useLogs } from "@/hooks/use-logs";
import type { Instance } from "@/lib/types";
import { BTN_GHOST } from "@/lib/ui";

export function LogsTab({ instance }: { instance: Instance }) {
  const { logs, isLoading, error, refresh } = useLogs(instance.id);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Logs do container</h2>
          <p className="mt-0.5 text-xs text-fg-3">Últimas 200 linhas do PostgreSQL (stdout/stderr).</p>
        </div>
        <button onClick={refresh} className={BTN_GHOST}>
          <RefreshCw size={13} /> Atualizar
        </button>
      </div>

      {isLoading ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
      ) : error ? (
        <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
      ) : !logs || !logs.trim() ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Sem logs para exibir.</p>
      ) : (
        // pre com scroll próprio: logs largos rolam sem quebrar o layout da página.
        <pre className="max-h-[28rem] overflow-auto px-4 py-3 font-mono text-xs leading-relaxed text-fg-2">
          {logs}
        </pre>
      )}
    </div>
  );
}
