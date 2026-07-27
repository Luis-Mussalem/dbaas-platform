"use client";

import { useState } from "react";
import { Plus, Trash2, RefreshCw, BellRing, Check } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createAlertRule,
  deleteAlertRule,
  updateAlertRule,
  seedDefaultAlertRules,
  resolveAlertEvent,
} from "@/lib/api";
import { useAlerts } from "@/hooks/use-alerts";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type {
  Instance,
  AlertRule,
  AlertEvent,
  AlertMetricType,
  AlertCondition,
  AlertSeverity,
} from "@/lib/types";
import { useFormatters } from "@/hooks/use-formatters";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST, INPUT } from "@/lib/ui";

// Unit shown next to each metric's threshold (the label comes from i18n).
// Mirrors the backend's AlertMetricType enum (src/schemas/alert.py).
const METRIC_UNITS: Record<AlertMetricType, string> = {
  connections_ratio: "%",
  cache_hit_ratio: "%",
  db_usage_percent: "%",
  long_query_seconds: "s",
  backup_age_hours: "h",
};

const CONDITIONS: Record<AlertCondition, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
};

const SEVERITY_CLS: Record<AlertSeverity, string> = {
  info: "text-info border-info/25 bg-info/10",
  warning: "text-warn border-warn/25 bg-warn/10",
  critical: "text-danger border-danger/25 bg-danger/10",
};
// Display order of the severity selector (the key is the source of the i18n label).
const SEVERITIES: AlertSeverity[] = ["info", "warning", "critical"];

// Initial state of the new-rule form. threshold is a string because it comes from
// an <input> (every HTML input delivers text); we convert it to a number on submit.
const EMPTY_FORM = {
  name: "",
  metric_type: "cache_hit_ratio" as AlertMetricType,
  condition: "lt" as AlertCondition,
  threshold: "",
  severity: "warning" as AlertSeverity,
};

export function AlertsTab({ instance }: { instance: Instance }) {
  const t = useTranslations("Alerts");
  const tc = useTranslations("Common");
  const { ago } = useFormatters();
  const { rules, events, isLoading, error, refresh } = useAlerts(instance.id);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { toast } = useToast();
  const { confirm } = useConfirm();

  // Immutable update: we never mutate `form` directly — we create a new object
  // with spread (...f) swapping only the changed field. The generic <K> guarantees that
  // value has the field's exact type (type-safety in the controlled input).
  function setField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function create() {
    const threshold = Number(form.threshold);
    if (!form.name.trim() || Number.isNaN(threshold)) {
      toast.error(t("toast.invalidForm"));
      return;
    }
    setBusy("create");
    try {
      await createAlertRule(instance.id, {
        name: form.name.trim(),
        metric_type: form.metric_type,
        condition: form.condition,
        threshold,
        severity: form.severity,
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      await refresh();
      toast.success(t("toast.created"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.createFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function seed() {
    setBusy("seed");
    try {
      await seedDefaultAlertRules(instance.id);
      await refresh();
      toast.success(t("toast.seeded"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.seedFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function toggle(rule: AlertRule) {
    setBusy(rule.id);
    try {
      await updateAlertRule(rule.id, { is_active: !rule.is_active });
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.updateFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function remove(rule: AlertRule) {
    const ok = await confirm({
      title: t("remove.title", { name: rule.name }),
      confirmText: tc("delete"),
      danger: true,
    });
    if (!ok) return;
    setBusy(rule.id);
    try {
      await deleteAlertRule(rule.id);
      await refresh();
      toast.success(t("toast.deleted"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.deleteFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function resolve(event: AlertEvent) {
    setBusy(event.id);
    try {
      await resolveAlertEvent(event.id);
      await refresh();
      toast.success(t("toast.resolved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toast.resolveFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ── Eventos ativos ── */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <BellRing size={14} className="text-warn" /> {t("activeTitle")}
            {events.length > 0 && (
              <span className="rounded-full bg-danger/15 px-1.5 py-0.5 text-[11px] font-medium text-danger">
                {events.length}
              </span>
            )}
          </h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> {tc("refresh")}
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : events.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("activeEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {events.map((ev) => (
              <li key={ev.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm text-foreground">{ev.message}</p>
                  <p className="mt-0.5 text-xs text-fg-3">
                    {t("valueLabel")}: <span className="font-mono">{ev.current_value}</span> ·{" "}
                    {ago(ev.triggered_at)}
                  </p>
                </div>
                <button
                  onClick={() => resolve(ev)}
                  disabled={busy !== null}
                  className={BTN}
                >
                  <Check size={13} /> {busy === ev.id ? t("resolving") : t("resolve")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Regras ── */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t("rulesTitle")}</h2>
          <div className="flex items-center gap-2">
            <button onClick={seed} disabled={busy !== null} className={BTN_GHOST}>
              {busy === "seed" ? t("seeding") : t("seed")}
            </button>
            <button
              onClick={() => setShowForm((v) => !v)}
              disabled={busy !== null}
              className={BTN}
            >
              <Plus size={13} /> {t("newRule")}
            </button>
          </div>
        </div>

        {/* creation form (controlled) */}
        {showForm && (
          <div className="flex flex-wrap items-end gap-3 border-b border-border bg-surface-2/40 px-4 py-3">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("form.name")}
              </span>
              <input
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
                placeholder={t("form.namePlaceholder")}
                className={cn(INPUT, "w-40")}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("form.metric")}
              </span>
              <select
                value={form.metric_type}
                onChange={(e) => setField("metric_type", e.target.value as AlertMetricType)}
                className={INPUT}
              >
                {(Object.keys(METRIC_UNITS) as AlertMetricType[]).map((m) => (
                  <option key={m} value={m}>
                    {t(`metrics.${m}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("form.condition")}
              </span>
              <select
                value={form.condition}
                onChange={(e) => setField("condition", e.target.value as AlertCondition)}
                className={INPUT}
              >
                {(Object.keys(CONDITIONS) as AlertCondition[]).map((c) => (
                  <option key={c} value={c}>
                    {CONDITIONS[c]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("form.threshold", { unit: METRIC_UNITS[form.metric_type] })}
              </span>
              <input
                type="number"
                value={form.threshold}
                onChange={(e) => setField("threshold", e.target.value)}
                placeholder="95"
                className={cn(INPUT, "w-24")}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("form.severity")}
              </span>
              <select
                value={form.severity}
                onChange={(e) => setField("severity", e.target.value as AlertSeverity)}
                className={INPUT}
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {t(`severity.${s}`)}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={create} disabled={busy !== null} className={BTN}>
              {busy === "create" ? tc("creating") : tc("create")}
            </button>
          </div>
        )}

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : rules.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("rulesEmpty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">{t("columns.name")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.condition")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.severity")}</th>
                <th className="px-4 py-2 font-medium">{t("columns.active")}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="px-4 py-2 text-foreground">{r.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-fg-2">
                    {t(`metrics.${r.metric_type}`)} {CONDITIONS[r.condition]} {r.threshold}
                    {METRIC_UNITS[r.metric_type]}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                        SEVERITY_CLS[r.severity]
                      )}
                    >
                      {t(`severity.${r.severity}`)}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => toggle(r)}
                      disabled={busy !== null}
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium transition disabled:opacity-50",
                        r.is_active
                          ? "bg-ok/10 text-ok hover:bg-ok/20"
                          : "bg-surface-2 text-fg-3 hover:bg-surface-2/70"
                      )}
                    >
                      {r.is_active ? t("state.active") : t("state.inactive")}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => remove(r)}
                      disabled={busy !== null}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-fg-3 transition hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                      aria-label={t("deleteRule")}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
