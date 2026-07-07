"use client";

import type { QueryResult } from "@/lib/types";

// Tabela de resultados do Console SQL. Apenas apresentação: recebe o QueryResult
// já carregado pela página e o renderiza. Segue o padrão visual de ConnectionsTable.
export function ResultsTable({ result }: { result: QueryResult }) {
  const { columns, rows, row_count, truncated } = result;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Resultado</h2>
        <span className="text-xs text-fg-3">
          {row_count} linha(s)
          {truncated && " · mostrando as primeiras 1000"}
        </span>
      </div>

      {columns.length === 0 ? (
        // SELECT válido que não devolve colunas (raro, mas possível).
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Query executada — sem linhas retornadas.
        </p>
      ) : (
        // overflow-x-auto: tabelas largas rolam na horizontal sem quebrar o layout.
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                {columns.map((col, i) => (
                  // Colunas podem repetir nome (SELECT 1, 1) → a key inclui o índice.
                  <th key={`${col}-${i}`} className="whitespace-nowrap px-4 py-2 font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Linhas não têm id próprio e podem se repetir (SELECT 1) — a key
                  combina conteúdo + posição para ser estável e única. */}
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
