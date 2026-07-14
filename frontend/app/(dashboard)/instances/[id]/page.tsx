"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ChevronLeft,
  Play,
  Square,
  Trash2,
  RefreshCw,
  Database,
} from "lucide-react";
import {
  getInstance,
  updateInstanceStatus,
  deleteInstance,
  getSlowQueries,
} from "@/lib/api";
import { useMetrics } from "@/hooks/use-metrics";
import { useMetricHistory } from "@/hooks/use-metric-history";
import { useToast } from "@/context/ToastProvider";
import { useConfirm } from "@/context/ConfirmProvider";
import type { Instance, SlowQuery } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { EnvBadge } from "@/components/EnvBadge";
import { RegionTag } from "@/components/RegionTag";
import { StatCard } from "@/components/StatCard";
import { ConnString } from "@/components/ConnString";
import { BackupsTab } from "@/components/BackupsTab";
import { MaintenanceTab } from "@/components/MaintenanceTab";
import { AlertsTab } from "@/components/AlertsTab";
import { MetricsTab } from "@/components/MetricsTab";
import { ReplicasTab } from "@/components/ReplicasTab";
import { LogsTab } from "@/components/LogsTab";
import { ConnectionsTable } from "@/components/ConnectionsTable";
import { SchemaExplorer } from "@/components/SchemaExplorer";
import { useFormatters } from "@/hooks/use-formatters";
import { cn } from "@/lib/utils";
import { BTN, BTN_DANGER } from "@/lib/ui";

// Os rótulos vêm de InstanceDetail.tabs.* — aqui só a ordem e os ids.
const TABS = [
  "overview",
  "metrics",
  "backups",
  "maintenance",
  "alerts",
  "replication",
  "logs",
] as const;

// Dias desde a criação ("ativo há Nd"), só informativo.
function daysSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

export default function InstanceDetailPage() {
  const t = useTranslations("InstanceDetail");
  const tc = useTranslations("Common");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [instance, setInstance] = useState<Instance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [tab, setTab] = useState("overview");

  const { metrics } = useMetrics(id);
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const load = useCallback(async () => {
    try {
      const data = await getInstance(id);
      setInstance(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("loadFailed"));
    } finally {
      setIsLoading(false);
    }
  }, [id, tc]);

  useEffect(() => {
    let active = true;
    getInstance(id)
      .then((data) => {
        if (active) {
          setInstance(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : tc("loadFailed"));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id, tc]);

  async function handleStatus(action: "start" | "stop") {
    if (!instance) return;
    setIsActing(true);
    setError(null);
    try {
      const updated = await updateInstanceStatus(instance.id, action);
      setInstance(updated);
      toast.success(action === "start" ? t("started") : t("stopped"));
    } catch (err) {
      const msg = err instanceof Error ? err.message : tc("error");
      setError(msg);
      toast.error(msg);
    } finally {
      setIsActing(false);
    }
  }

  async function handleDelete() {
    if (!instance) return;
    const ok = await confirm({
      title: t("deleteConfirm", { name: instance.name }),
      description: t("deleteConfirmSub"),
      confirmText: tc("delete"),
      danger: true,
    });
    if (!ok) return;
    setIsActing(true);
    setError(null);
    try {
      await deleteInstance(instance.id);
      toast.success(t("deleted", { name: instance.name }));
      router.push("/instances");
    } catch (err) {
      const msg = err instanceof Error ? err.message : tc("error");
      setError(msg);
      toast.error(msg);
      setIsActing(false);
    }
  }

  if (isLoading) return <p className="text-sm text-fg-3">{tc("loading")}</p>;
  if (!instance)
    return <p className="text-sm text-danger">{error ?? t("notFound")}</p>;

  const canStart = instance.status === "stopped" || instance.status === "failed";
  const canStop = instance.status === "running";
  const canDelete = instance.status === "stopped" || instance.status === "failed";

  const ramGb = instance.memory_mb ? instance.memory_mb / 1024 : null;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Hero ── */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.back()}
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <ChevronLeft size={16} />
            </button>
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-linear-to-br from-primary to-info text-primary-foreground">
              <Database size={18} />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-mono text-xl font-semibold">{instance.name}</h1>
                <StatusBadge status={instance.status} />
                <EnvBadge environment={instance.environment} />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
                <span>PostgreSQL {instance.engine_version}</span>
                {instance.region && (
                  <>
                    <span className="text-fg-faint">·</span>
                    <RegionTag region={instance.region} />
                  </>
                )}
                <span className="text-fg-faint">·</span>
                <span>{instance.cpu ?? "—"} vCPU · {ramGb ?? "—"} GB RAM · {instance.storage_gb ?? "—"} GB</span>
                <span className="text-fg-faint">·</span>
                <span>{t("activeFor", { days: daysSince(instance.created_at) })}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button onClick={load} disabled={isActing} className={BTN}>
              <RefreshCw size={13} /> {t("refresh")}
            </button>
            {canStart && (
              <button onClick={() => handleStatus("start")} disabled={isActing} className={BTN}>
                <Play size={13} /> {isActing ? t("starting") : t("start")}
              </button>
            )}
            {canStop && (
              <button onClick={() => handleStatus("stop")} disabled={isActing} className={BTN}>
                <Square size={13} /> {isActing ? t("stopping") : t("stop")}
              </button>
            )}
            {canDelete && (
              <button onClick={handleDelete} disabled={isActing} className={BTN_DANGER}>
                <Trash2 size={13} /> {tc("delete")}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        {instance.host && (
          <div className="mt-4">
            <ConnString
              host={instance.host}
              port={instance.port}
              db={instance.db_name}
              user={instance.db_user}
            />
          </div>
        )}

        {/* ── Abas ── */}
        <div className="mt-4 flex gap-1 overflow-x-auto border-b border-border">
          {TABS.map((id) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "-mb-px shrink-0 border-b-2 px-3 py-2 text-[13px] font-medium transition",
                tab === id
                  ? "border-brand text-brand"
                  : "border-transparent text-fg-3 hover:text-fg-2"
              )}
            >
              {t(`tabs.${id}`)}
            </button>
          ))}
        </div>
      </div>

      {/* ── Conteúdo da aba ── */}
      {tab === "overview" && <OverviewTab instance={instance} metrics={metrics?.metrics ?? {}} />}
      {tab === "metrics" && <MetricsTab instance={instance} />}
      {tab === "backups" && <BackupsTab instance={instance} />}
      {tab === "maintenance" && <MaintenanceTab instance={instance} />}
      {tab === "alerts" && <AlertsTab instance={instance} />}
      {tab === "replication" && <ReplicasTab instance={instance} />}
      {tab === "logs" && <LogsTab instance={instance} />}
    </div>
  );
}

// ── Aba: Visão geral ──
function OverviewTab({
  instance,
  metrics,
}: {
  instance: Instance;
  metrics: Record<string, number>;
}) {
  const t = useTranslations("InstanceDetail");
  const tc = useTranslations("Common");
  const { bytes, ratio } = useFormatters();
  const connActive = metrics.connections_active;
  const connMax = metrics.connections_max;
  const cacheHit = metrics.cache_hit_ratio;
  const sizeBytes = metrics.db_size_bytes;

  // Sparkline real de conexões (últimas 24h) para o primeiro card.
  const connHistory = useMetricHistory(instance.id, "connections_active", "24h");

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label={t("connections.label")}
          value={
            connActive != null
              ? `${Math.round(connActive)}${connMax ? `/${Math.round(connMax)}` : ""}`
              : tc("none")
          }
          sub={t("connections.activeMax")}
          chart={connHistory.length > 1 ? connHistory : undefined}
        />
        <StatCard
          label={t("cacheHit")}
          value={cacheHit != null ? `${ratio(cacheHit)}%` : tc("none")}
          sub={t("cacheHitTarget")}
          accent={cacheHit != null && cacheHit < 95 ? "warn" : "ok"}
        />
        <StatCard label={t("size")} value={bytes(sizeBytes)} sub={t("database")} />
        <StatCard label={t("status")} value={instance.status} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <ConnectionsTable instance={instance} />
        <SchemaExplorer instance={instance} />
      </div>

      <SlowQueries instance={instance} />
    </div>
  );
}

// ── Tabela de queries lentas (pg_stat_statements) ──
function SlowQueries({ instance }: { instance: Instance }) {
  const t = useTranslations("InstanceDetail");
  const tc = useTranslations("Common");
  const [rows, setRows] = useState<SlowQuery[] | null>(null);
  const [failed, setFailed] = useState(false);
  const running = instance.status === "running";

  useEffect(() => {
    if (!running) return;
    let active = true;
    getSlowQueries(instance.id)
      .then((r) => active && setRows(r.queries))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [instance.id, running]);

  // Parada → tratamos como lista vazia (sem dados), não como indisponível.
  const unavailable = failed;
  const display = running ? rows : [];

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{t("slowQueries.title")}</h2>
        <span className="text-xs text-fg-3">pg_stat_statements</span>
      </div>

      {unavailable ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("unavailableStopped")}</p>
      ) : display === null ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
      ) : display.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Sem queries lentas registradas.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">{t("slowQueries.query")}</th>
              <th className="px-4 py-2 text-right font-medium">{t("slowQueries.avg")}</th>
              <th className="px-4 py-2 text-right font-medium">{t("slowQueries.calls")}</th>
            </tr>
          </thead>
          <tbody>
            {/* pg_stat_statements normaliza as queries — o texto é único por linha. */}
            {display.map((q) => (
              <tr key={q.query} className="border-t border-border">
                <td className="max-w-0 truncate px-4 py-2 font-mono text-xs text-fg-2">
                  {q.query}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-warn">
                  {q.mean_exec_time_ms} ms
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right font-mono">{q.calls}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
