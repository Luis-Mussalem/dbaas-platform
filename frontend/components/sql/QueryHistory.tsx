"use client";

import { History, X } from "lucide-react";
import { useTranslations } from "next-intl";

// Query history (pure presentation). The page owns the list and the
// localStorage persistence; here we just list them and report clicks.
export function QueryHistory({
  items,
  onSelect,
  onClear,
}: {
  items: string[];
  onSelect: (query: string) => void;
  onClear: () => void;
}) {
  const t = useTranslations("Sql.history");

  if (items.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <History size={14} className="text-fg-3" />
          {t("title")}
        </h2>
        <button
          onClick={onClear}
          className="flex items-center gap-1 text-xs text-fg-3 transition-colors hover:text-foreground"
        >
          <X size={12} />
          {t("clear")}
        </button>
      </div>
      <ul className="p-2">
        {/* The history is deduplicated on save — the query itself is the key. */}
        {items.map((q) => (
          <li key={q}>
            <button
              onClick={() => onSelect(q)}
              title={t("load")}
              className="block w-full truncate rounded-md px-2 py-1.5 text-left font-mono text-xs text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
