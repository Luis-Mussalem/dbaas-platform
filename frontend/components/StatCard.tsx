import type { ReactNode } from "react";

// Card de KPI — rótulo + número grande + linha de apoio (sub).
// O `accent` colore a linha de apoio (verde/amarelo/vermelho) conforme o estado.
export function StatCard({
  label,
  value,
  sub,
  accent = "default",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: "default" | "ok" | "warn" | "danger";
}) {
  const accentClass = {
    default: "text-fg-3",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  }[accent];

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-surface p-4">
      <span className="text-[11.5px] font-medium uppercase tracking-wide text-fg-3">
        {label}
      </span>
      <span className="font-mono text-2xl font-semibold tabular-nums">{value}</span>
      {sub && <span className={`text-[11.5px] ${accentClass}`}>{sub}</span>}
    </div>
  );
}
