"use client";

import { useTranslations } from "next-intl";
import type { QueryResult } from "@/lib/types";

// Mirrors MAX_ROWS from backend/src/services/query.py — the cap doesn't come in the response,
// only the `truncated` boolean.
const MAX_ROWS = 1000;

// SQL Console results table. Presentation only: receives the QueryResult
// already loaded by the page and renders it. Follows ConnectionsTable's visual pattern.
export function ResultsTable({ result }: { result: QueryResult }) {
  const t = useTranslations("Sql.results");
  const { columns, rows, row_count, truncated } = result;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <span className="text-xs text-fg-3">
          {t("rows", { count: row_count })}
          {truncated && ` · ${t("truncated", { limit: MAX_ROWS })}`}
        </span>
      </div>

      {columns.length === 0 ? (
        // A valid SELECT that returns no columns (rare, but possible).
        <p className="px-4 py-8 text-center text-sm text-fg-3">{t("noRows")}</p>
      ) : (
        // overflow-x-auto: wide tables scroll horizontally without breaking the layout.
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                {columns.map((col, i) => (
                  // Columns can repeat a name (SELECT 1, 1) → the key includes the index.
                  <th key={`${col}-${i}`} className="whitespace-nowrap px-4 py-2 font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Rows have no id of their own and can repeat (SELECT 1) — the key
                  combines content + position to be stable and unique. */}
              {rows.map((row, r) => (
                <tr key={`${r}|${row.join("")}`} className="border-t border-border">
                  {row.map((cell, c) => (
                    <td
                      key={c}
                      className="whitespace-nowrap px-4 py-2 font-mono text-xs text-fg-2"
                    >
                      {cell === null ? (
                        <span className="italic text-fg-3">NULL</span>
                      ) : (
                        cell
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
