"use client";

import { useEffect, useState } from "react";
import { getConnections } from "@/lib/api";
import type { ActiveConnection, Instance } from "@/lib/types";

// Cor do estado da conexão (espelha o vocabulário do pg_stat_activity).
function stateTone(state: string | null): string {
  if (state === "active") return "text-ok border-ok/25 bg-ok/10";
  if (state === "idle in transaction") return "text-warn border-warn/25 bg-warn/10";
  return "text-fg-3 border-border bg-bg-2"; // idle e outros
}

// Duração em segundos → "12 ms" / "3.2 s".
function dur(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  return `${seconds.toFixed(1)} s`;
}

export function ConnectionsTable({ instance }: { instance: Instance }) {
  const [rows, setRows] = useState<ActiveConnection[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    // Endpoint live: só faz sentido com a instância RUNNING.
    if (instance.status !== "running") {
      setRows([]);
      setUnavailable(true);
      return;
    }
    let active = true;
    getConnections(instance.id)
      .then((r) => active && setRows(r.connections))
      .catch(() => active && setUnavailable(true));
    return () => {
      active = false;
    };
  }, [instance.id, instance.status]);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Conexões ativas</h2>
        <span className="text-xs text-fg-3">pg_stat_activity</span>
      </div>

      {unavailable ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Indisponível (instância parada).
        </p>
      ) : rows === null ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
      ) : rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Nenhuma conexão ativa.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">PID</th>
              <th className="px-4 py-2 font-medium">Usuário</th>
              <th className="px-4 py-2 font-medium">Estado</th>
              <th className="px-4 py-2 text-right font-medium">Espera</th>
              <th className="px-4 py-2 font-medium">Query</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.pid} className="border-t border-border">
                <td className="px-4 py-2 font-mono text-xs">{c.pid}</td>
                <td className="px-4 py-2 text-fg-2">{c.user ?? "—"}</td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${stateTone(
                      c.state
                    )}`}
                  >
                    {c.state ?? "—"}
                  </span>
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-xs text-fg-3">
                  {dur(c.duration_seconds)}
                </td>
                <td className="max-w-0 truncate px-4 py-2 font-mono text-xs text-fg-2">
                  {c.query || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
