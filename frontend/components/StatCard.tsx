import type { ReactNode } from "react";
import { Sparkline } from "@/components/Sparkline";

// KPI card — label + large number + support line (sub) + optional sparkline.
// `accent` colors the support line (green/yellow/red) according to the state.
// `chart` (optional) draws a sparkline in the footer, in the design's card style.
export function StatCard({
  label,
  value,
  sub,
  accent = "default",
  chart,
  chartColor = "var(--brand)",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: "default" | "ok" | "warn" | "danger";
  chart?: number[];
  chartColor?: string;
}) {
  const accentClass = {
    default: "text-fg-3",
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
  }[accent];

  return (
    <div className="flex flex-col gap-1.5 overflow-hidden rounded-lg border border-border bg-surface p-4">
      <span className="text-[11.5px] font-medium uppercase tracking-wide text-fg-3">
        {label}
      </span>
      <span className="font-mono text-2xl font-semibold tabular-nums">{value}</span>
      {sub && <span className={`text-[11.5px] ${accentClass}`}>{sub}</span>}
      {chart && chart.length > 0 && (
        <Sparkline data={chart} color={chartColor} className="mt-1 h-8 w-full" />
      )}
    </div>
  );
}
