"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { TriangleAlert, DatabaseBackup, ShieldCheck, Info } from "lucide-react";
import type { Instance, InstanceSummary } from "@/lib/types";
import { useMetricHistory } from "@/hooks/use-metric-history";
import { DASHBOARD_POLL_MS } from "@/lib/constants";
import { useFormatters } from "@/hooks/use-formatters";
import { instanceGradient, instanceInitials, instanceLineColor, instanceInk } from "@/lib/identity-color";
import { HealthBadge } from "@/components/StatusBadge";
import { EnvBadge } from "@/components/EnvBadge";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { RegionTag } from "@/components/RegionTag";
import { Sparkline } from "@/components/Sparkline";

// Minimum width of the storage bar, in %. A small database on a big plan
// gives a fraction of 1%: without a floor, the bar disappears and the card suggests "no data"
// when the reading is actually fine.
const MIN_BAR_PCT = 1.5;

export function InstanceCard({
  instance,
  summary,
  qpsScaleMax,
}: {
  instance: Instance;
  // Absent while the fleet aggregate is loading — the card renders without it.
  summary?: InstanceSummary;
  // Y ceiling common to all cards (zero-based) for the queries/s sparkline: the
  // line's height starts to encode magnitude, comparable across cards. Absent
  // → the sparkline auto-scales to its own range (fallback).
  qpsScaleMax?: number;
}) {
  const t = useTranslations("InstanceCard");
  const tc = useTranslations("Common");
  const { bytes, ratio, number, ago } = useFormatters();

  // REAL sparkline: queries/s history — the SAME quantity as the number the
  // card highlights, so the chart and the number tell a single story
  // (connections stays as a number on the card and as a chart on the detail screen).
  // queries/s isn't stored: the endpoint derives the series from the xact_commit counter.
  // Empty → Sparkline shows a baseline.
  //
  // 15m window in 60 buckets = one bucket per COLLECTION (15s): every poller write
  // becomes a point, so the line reflects the data's real resolution, without 1 min
  // averages that used to blur the 15s writes. The card shows the present; the hours
  // view stays on the detail screen, where there's room to read it.
  const throughputHistory = useMetricHistory(
    instance.id,
    "queries_per_second",
    "15m",
    DASHBOARD_POLL_MS,
    60
  );

  // All scalar values come from the fleet aggregate: one request serves
  // the whole grid, instead of a GET /metrics per card on every poll.
  const connActive = summary?.connections_active;
  const connMax = summary?.connections_max;
  const sizeBytes = summary?.db_size_bytes;

  // Storage bar: current database size vs. contracted capacity.
  const capacityBytes = instance.storage_gb ? instance.storage_gb * 1024 ** 3 : null;
  const storagePct =
    capacityBytes && sizeBytes ? Math.min(100, (sizeBytes / capacityBytes) * 100) : null;

  const growth = summary?.size_delta_24h_bytes;
  const growthDirection = growth == null || growth === 0 ? "flat" : growth > 0 ? "up" : "down";

  // The sparkline's line uses the country's IDENTITY color (same as the avatar),
  // except when failed — there the status red prevails as a strong signal.
  const sparkColor =
    instance.status === "failed"
      ? "var(--danger)"
      : instanceLineColor(instance.region, instance.environment);

  const openAlerts = summary?.open_alerts ?? 0;
  const alertColor =
    summary?.max_alert_severity === "critical" ? "var(--danger)" : "var(--warn)";

  return (
    <Link
      href={`/instances/${instance.id}`}
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
    >
      {/* top: icon + name + region  ·  health */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* avatar with the COUNTRY's identity color (hue) + tone by environment */}
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-[11px] font-bold"
            style={{
              backgroundImage: instanceGradient(instance.region, instance.environment),
              color: instanceInk(instance.region),
            }}
          >
            {instanceInitials(instance.name)}
          </div>
          <div className="min-w-0">
            <div className="truncate text-[14.5px] font-semibold text-foreground">
              {instance.name}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-fg-3">
              <RegionTag region={instance.region} />
              {instance.region && <span className="text-fg-faint">·</span>}
              <span>PostgreSQL {instance.engine_version}</span>
            </div>
          </div>
        </div>
        <HealthBadge status={instance.status} />
      </div>

      {/* environment (tag) · open alerts */}
      <div className="flex items-center justify-between gap-2">
        {instance.environment ? <EnvBadge environment={instance.environment} /> : <span />}
        {openAlerts > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium"
            style={{ color: alertColor, backgroundColor: `color-mix(in srgb, ${alertColor} 14%, transparent)` }}
          >
            <TriangleAlert className="h-3 w-3" />
            {t("openAlerts", { count: openAlerts })}
          </span>
        )}
      </div>

      {/* sparkline caption: without it, the line looked decorative — nothing on the
          card said it's queries/s (the same quantity as the "throughput" number
          right below) and not connections or latency. The native tooltip (title)
          carries the update cadence, the same pattern as the copy button in
          ConnString.tsx. */}
      <div className="flex flex-col gap-1">
        <div
          className="flex items-center gap-1 text-[11px] text-fg-3"
          title={t("throughputTooltip", { seconds: DASHBOARD_POLL_MS / 1000 })}
        >
          <span>{t("throughputCaption")}</span>
          <Info className="h-3 w-3 shrink-0 text-fg-faint" aria-hidden />
        </div>
        {/* real sparkline: queries/s over the last hour, on a shared (zero-based)
            scale so the height is comparable across cards */}
        <Sparkline
          data={throughputHistory}
          color={sparkColor}
          domainMin={0}
          domainMax={qpsScaleMax}
          className="h-14 w-full"
        />
      </div>

      {/* live metrics: the three that move with the load */}
      <div className="flex items-center justify-between">
        <Metric
          label={t("connections")}
          value={
            connActive != null
              ? `${Math.round(connActive)}${connMax ? `/${Math.round(connMax)}` : ""}`
              : tc("none")
          }
        />
        <Metric
          label={t("throughput")}
          value={
            summary?.queries_per_second != null
              ? (
                <AnimatedNumber
                  value={summary.queries_per_second}
                  format={(n) => number(Math.round(n))}
                />
              )
              : tc("none")
          }
          align="right"
          // Same color as the sparkline's line right above: the number that stands out
          // on the card now reads as "the value FROM THAT chart", not a loose data point.
          valueColor={sparkColor}
        />
        <Metric
          label={t("p95")}
          value={
            summary?.p95_latency_ms != null
              ? t("milliseconds", { value: ratio(summary.p95_latency_ms) })
              : tc("none")
          }
          align="right"
        />
      </div>

      {/* storage: used / plan, with growth over the last 24h */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-fg-3">
          <span>{t("storage")}</span>
          <span className="font-mono text-fg-2">
            {capacityBytes
              ? t("capacity", { used: bytes(sizeBytes), total: bytes(capacityBytes) })
              : bytes(sizeBytes)}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-bg-2">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: storagePct ? `${Math.max(storagePct, MIN_BAR_PCT)}%` : "0%",
              backgroundColor: (storagePct ?? 0) > 85 ? "var(--warn)" : "var(--brand)",
            }}
          />
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[11.5px] text-fg-3">
          <span className="font-mono">
            {storagePct != null ? `${ratio(storagePct)}%` : tc("none")}
          </span>
          {growth != null && (
            <span>
              {t("growth24h", {
                direction: growthDirection,
                size: bytes(Math.abs(growth)),
              })}
            </span>
          )}
        </div>
      </div>

      {/* footer: operational signals — what a DBA checks before opening the instance */}
      <div className="flex items-center gap-3 border-t border-border pt-2.5 text-[11.5px] text-fg-3">
        <span className="inline-flex items-center gap-1.5">
          <DatabaseBackup className="h-3.5 w-3.5 shrink-0" />
          {summary?.last_backup_at
            ? summary.last_backup_status === "failed"
              ? t("backupFailed")
              : t("backupAgo", { ago: ago(summary.last_backup_at) })
            : t("backupNone")}
        </span>
        {summary?.uptime_30d_pct != null && (
          <span className="ml-auto inline-flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
            {t("uptime30d", { pct: ratio(summary.uptime_30d_pct, 2) })}
          </span>
        )}
      </div>
    </Link>
  );
}

function Metric({
  label,
  value,
  align = "left",
  valueColor,
}: {
  label: string;
  value: React.ReactNode;
  align?: "left" | "right";
  // Color of the highlighted value — used to match the number with the color of the
  // sparkline line it describes. Absent → the card's default text color.
  valueColor?: string;
}) {
  return (
    <div className={align === "right" ? "text-right" : ""}>
      <div
        className="font-mono text-base font-semibold tabular-nums"
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </div>
      <div className="text-[11.5px] text-fg-3">{label}</div>
    </div>
  );
}
