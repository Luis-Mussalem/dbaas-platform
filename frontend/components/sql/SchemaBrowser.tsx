"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Table2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { getSchema } from "@/lib/api";
import type { Instance, SchemaGroup } from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";

// Variant of SchemaExplorer for the SQL Console: each table is a button that
// calls onPickTable(name) — the page inserts the name into the editor. Same look and
// the same data source (getSchema), only the interaction changes (clickable).
export function SchemaBrowser({
  instance,
  onPickTable,
}: {
  instance: Instance;
  onPickTable: (table: string) => void;
}) {
  const t = useTranslations("Sql.schema");
  const tc = useTranslations("Common");
  const { number } = useFormatters();
  const [groups, setGroups] = useState<SchemaGroup[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set(["public"]));

  // The page remounts this component via `key={instance.id}` when switching
  // instances, so the state already resets on its own — the effect only triggers the fetch and
  // "stopped" is derived at render time.
  useEffect(() => {
    if (instance.status !== "running") return;
    let active = true;
    getSchema(instance.id)
      .then((r) => active && setGroups(r.schemas))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [instance.id, instance.status]);

  const unavailable = instance.status !== "running" || failed;

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
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <span className="text-xs text-fg-3">pg_class</span>
      </div>

      {unavailable ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("unavailableStopped")}</p>
      ) : groups === null ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
      ) : groups.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
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
                    {g.tables.map((tbl) => (
                      <li key={tbl.table}>
                        <button
                          onClick={() => onPickTable(tbl.table)}
                          title={t("insert")}
                          className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
                        >
                          <Table2 size={12} className="shrink-0 text-fg-3" />
                          <span className="flex-1 truncate font-mono">{tbl.table}</span>
                          <span className="font-mono text-[11px] text-fg-3">
                            {number(tbl.estimated_rows)}
                          </span>
                        </button>
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
