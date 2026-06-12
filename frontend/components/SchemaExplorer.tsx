"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Table2 } from "lucide-react";
import { getSchema } from "@/lib/api";
import type { Instance, SchemaGroup } from "@/lib/types";
import { formatNumber } from "@/lib/format";

export function SchemaExplorer({ instance }: { instance: Instance }) {
  const [groups, setGroups] = useState<SchemaGroup[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  // Quais schemas estão expandidos (Set de nomes). public começa aberto.
  const [open, setOpen] = useState<Set<string>>(new Set(["public"]));

  useEffect(() => {
    if (instance.status !== "running") {
      setGroups([]);
      setUnavailable(true);
      return;
    }
    let active = true;
    getSchema(instance.id)
      .then((r) => active && setGroups(r.schemas))
      .catch(() => active && setUnavailable(true));
    return () => {
      active = false;
    };
  }, [instance.id, instance.status]);

  function toggle(name: string) {
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Explorador de esquemas</h2>
        <span className="text-xs text-fg-3">pg_class</span>
      </div>

      {unavailable ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Indisponível (instância parada).
        </p>
      ) : groups === null ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
      ) : groups.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Sem tabelas de usuário.</p>
      ) : (
        <ul className="p-2">
          {groups.map((g) => {
            const expanded = open.has(g.name);
            return (
              <li key={g.name}>
                <button
                  onClick={() => toggle(g.name)}
                  className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[13px] font-medium transition-colors hover:bg-surface-2"
                >
                  {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <span className="flex-1">{g.name}</span>
                  <span className="text-[11px] text-fg-3">{g.tables.length}</span>
                </button>
                {expanded && (
                  <ul className="ml-3 border-l border-border pl-3">
                    {g.tables.map((t) => (
                      <li
                        key={t.table}
                        className="flex items-center gap-2 py-1 text-[12.5px] text-fg-2"
                      >
                        <Table2 size={12} className="shrink-0 text-fg-3" />
                        <span className="flex-1 truncate font-mono">{t.table}</span>
                        <span className="font-mono text-[11px] text-fg-3">
                          {formatNumber(t.estimated_rows)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
