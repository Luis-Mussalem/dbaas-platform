"use client";

import { History, X } from "lucide-react";

// Histórico de queries (apresentação pura). A página é dona da lista e da
// persistência em localStorage; aqui só listamos e avisamos cliques.
export function QueryHistory({
  items,
  onSelect,
  onClear,
}: {
  items: string[];
  onSelect: (query: string) => void;
  onClear: () => void;
}) {
  if (items.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <History size={14} className="text-fg-3" />
          Histórico
        </h2>
        <button
          onClick={onClear}
          className="flex items-center gap-1 text-xs text-fg-3 transition-colors hover:text-foreground"
        >
          <X size={12} />
          Limpar
        </button>
      </div>
      <ul className="p-2">
        {items.map((q, i) => (
          <li key={i}>
            <button
              onClick={() => onSelect(q)}
              title="Carregar no editor"
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
