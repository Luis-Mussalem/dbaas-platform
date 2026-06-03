"use client";

import { useState } from "react";
import { Plus, Trash2, RefreshCw, BellRing, Check } from "lucide-react";
import {
  createAlertRule,
  deleteAlertRule,
  updateAlertRule,
  seedDefaultAlertRules,
  resolveAlertEvent,
} from "@/lib/api";
import { useAlerts } from "@/hooks/use-alerts";
import type {
  Instance,
  AlertRule,
  AlertEvent,
  AlertMetricType,
  AlertCondition,
  AlertSeverity,
} from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const BTN =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";
const BTN_GHOST =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";
const INPUT =
  "h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground outline-none transition focus:border-brand";

// Metadados de cada métrica: rótulo legível + unidade exibida ao lado do limiar.
// Espelha o enum AlertMetricType do backend (src/schemas/alert.py).
const METRICS: Record<AlertMetricType, { label: string; unit: string }> = {
  connections_ratio: { label: "Uso de conexões", unit: "%" },
  cache_hit_ratio: { label: "Cache hit", unit: "%" },
  db_usage_percent: { label: "Uso de disco", unit: "%" },
  long_query_seconds: { label: "Query mais longa", unit: "s" },
  backup_age_hours: { label: "Idade do backup", unit: "h" },
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
const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  info: "Info",
  warning: "Atenção",
  critical: "Crítico",
};

// Estado inicial do formulário de nova regra. threshold é string porque vem de
// um <input> (todo input HTML entrega texto); convertemos para número no envio.
const EMPTY_FORM = {
  name: "",
  metric_type: "cache_hit_ratio" as AlertMetricType,
  condition: "lt" as AlertCondition,
  threshold: "",
  severity: "warning" as AlertSeverity,
};

export function AlertsTab({ instance }: { instance: Instance }) {
  const { rules, events, isLoading, error, refresh } = useAlerts(instance.id);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Atualização imutável: nunca mutamos `form` direto — criamos um objeto novo
  // com spread (...f) trocando só o campo alterado. O genérico <K> garante que
  // value tenha o tipo exato do campo (type-safety no controlled input).
  function setField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function create() {
    const threshold = Number(form.threshold);
    if (!form.name.trim() || Number.isNaN(threshold)) {
      setActionError("Informe um nome e um limiar numérico.");
      return;
    }
    setBusy("create");
    setActionError(null);
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
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao criar regra");
    } finally {
      setBusy(null);
    }
  }

  async function seed() {
    setBusy("seed");
    setActionError(null);
    try {
      await seedDefaultAlertRules(instance.id);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao semear padrões");
    } finally {
      setBusy(null);
    }
  }

  async function toggle(rule: AlertRule) {
    setBusy(rule.id);
    setActionError(null);
    try {
      await updateAlertRule(rule.id, { is_active: !rule.is_active });
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao atualizar regra");
    } finally {
      setBusy(null);
    }
  }

  async function remove(rule: AlertRule) {
    if (!window.confirm(`Excluir a regra "${rule.name}"?`)) return;
    setBusy(rule.id);
    setActionError(null);
    try {
      await deleteAlertRule(rule.id);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao excluir regra");
    } finally {
      setBusy(null);
    }
  }

  async function resolve(event: AlertEvent) {
    setBusy(event.id);
    setActionError(null);
    try {
      await resolveAlertEvent(event.id);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha ao resolver evento");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {actionError && (
        <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {actionError}
        </div>
      )}

      {/* ── Eventos ativos ── */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <BellRing size={14} className="text-warn" /> Alertas ativos
            {events.length > 0 && (
              <span className="rounded-full bg-danger/15 px-1.5 py-0.5 text-[11px] font-medium text-danger">
                {events.length}
              </span>
            )}
          </h2>
          <button onClick={refresh} className={BTN_GHOST}>
            <RefreshCw size={13} /> Atualizar
          </button>
        </div>

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
        ) : events.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">
            Nenhum alerta ativo. 🎉
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {events.map((ev) => (
              <li key={ev.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm text-foreground">{ev.message}</p>
                  <p className="mt-0.5 text-xs text-fg-3">
                    valor: <span className="font-mono">{ev.current_value}</span> ·{" "}
                    {timeAgo(ev.triggered_at)}
                  </p>
                </div>
                <button
                  onClick={() => resolve(ev)}
                  disabled={busy !== null}
                  className={BTN}
                >
                  <Check size={13} /> {busy === ev.id ? "Resolvendo…" : "Resolver"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Regras ── */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Regras de alerta</h2>
          <div className="flex items-center gap-2">
            <button onClick={seed} disabled={busy !== null} className={BTN_GHOST}>
              {busy === "seed" ? "Semeando…" : "Semear padrões"}
            </button>
            <button
              onClick={() => setShowForm((v) => !v)}
              disabled={busy !== null}
              className={BTN}
            >
              <Plus size={13} /> Nova regra
            </button>
          </div>
        </div>

        {/* formulário de criação (controlado) */}
        {showForm && (
          <div className="flex flex-wrap items-end gap-3 border-b border-border bg-surface-2/40 px-4 py-3">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">Nome</span>
              <input
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
                placeholder="Cache baixo"
                className={cn(INPUT, "w-40")}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">Métrica</span>
              <select
                value={form.metric_type}
                onChange={(e) => setField("metric_type", e.target.value as AlertMetricType)}
                className={INPUT}
              >
                {(Object.keys(METRICS) as AlertMetricType[]).map((m) => (
                  <option key={m} value={m}>
                    {METRICS[m].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">Condição</span>
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
                Limiar ({METRICS[form.metric_type].unit})
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
              <span className="text-[11px] uppercase tracking-wide text-fg-3">Severidade</span>
              <select
                value={form.severity}
                onChange={(e) => setField("severity", e.target.value as AlertSeverity)}
                className={INPUT}
              >
                {(Object.keys(SEVERITY_LABEL) as AlertSeverity[]).map((s) => (
                  <option key={s} value={s}>
                    {SEVERITY_LABEL[s]}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={create} disabled={busy !== null} className={BTN}>
              {busy === "create" ? "Criando…" : "Criar"}
            </button>
          </div>
        )}

        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : rules.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">
            Nenhuma regra. Use “Semear padrões” para começar.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">Nome</th>
                <th className="px-4 py-2 font-medium">Condição</th>
                <th className="px-4 py-2 font-medium">Severidade</th>
                <th className="px-4 py-2 font-medium">Ativa</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="px-4 py-2 text-foreground">{r.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-fg-2">
                    {METRICS[r.metric_type]?.label ?? r.metric_type} {CONDITIONS[r.condition]}{" "}
                    {r.threshold}
                    {METRICS[r.metric_type]?.unit}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                        SEVERITY_CLS[r.severity]
                      )}
                    >
                      {SEVERITY_LABEL[r.severity]}
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
                      {r.is_active ? "Ativa" : "Inativa"}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => remove(r)}
                      disabled={busy !== null}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-fg-3 transition hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                      aria-label="Excluir regra"
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
