"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
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
import type { Instance, SlowQuery } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { StatCard } from "@/components/StatCard";
import { ConnString } from "@/components/ConnString";
import { BackupsTab } from "@/components/BackupsTab";
import { MaintenanceTab } from "@/components/MaintenanceTab";
import { AlertsTab } from "@/components/AlertsTab";
import { EmptyState } from "@/components/EmptyState";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "overview", label: "Visão geral" },
  { id: "backups", label: "Backups" },
  { id: "maintenance", label: "Manutenção" },
  { id: "alerts", label: "Alertas" },
  { id: "metrics", label: "Métricas" },
  { id: "logs", label: "Logs" },
];

const BTN_SM =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-[13px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";
const BTN_DANGER =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-danger/30 px-3 text-[13px] font-medium text-danger transition hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50";

export default function InstanceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [instance, setInstance] = useState<Instance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [tab, setTab] = useState("overview");

  const { metrics } = useMetrics(id);

  // useCallback: mantém a mesma referência da função entre renders, para o
  // botão "Atualizar" e o useEffect compartilharem a mesma busca.
  const load = useCallback(async () => {
    try {
      const data = await getInstance(id);
      setInstance(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar");
    } finally {
      setIsLoading(false);
    }
  }, [id]);

  // Busca inicial inline (setState dentro do .then/.catch) — evita o aviso de
  // "setState síncrono no effect". O botão "Atualizar" segue usando `load`.
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
        if (active) setError(err instanceof Error ? err.message : "Falha ao carregar");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);

  async function handleStatus(action: "start" | "stop") {
    if (!instance) return;
    setIsActing(true);
    setError(null);
    try {
      const updated = await updateInstanceStatus(instance.id, action);
      setInstance(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ação falhou");
    } finally {
      setIsActing(false);
    }
  }

  async function handleDelete() {
    if (!instance) return;
    if (
      !window.confirm(
        `Excluir "${instance.name}"? Esta ação não pode ser desfeita.`
      )
    )
      return;
    setIsActing(true);
    setError(null);
    try {
      await deleteInstance(instance.id);
      router.push("/instances");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao excluir");
      setIsActing(false);
    }
  }

  if (isLoading) return <p className="text-sm text-fg-3">Carregando…</p>;
  if (!instance)
    return <p className="text-sm text-danger">{error ?? "Instância não encontrada"}</p>;

  // Estado derivado das ações (alinhado às regras do backend).
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
              <div className="flex items-center gap-2">
                <h1 className="font-mono text-xl font-semibold">{instance.name}</h1>
                <StatusBadge status={instance.status} />
              </div>
              <div className="mt-0.5 text-xs text-fg-3">
                PostgreSQL {instance.engine_version} · {instance.cpu ?? "—"} vCPU ·{" "}
                {ramGb ?? "—"} GB RAM · {instance.storage_gb ?? "—"} GB SSD
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button onClick={load} disabled={isActing} className={BTN_SM}>
              <RefreshCw size={13} /> Atualizar
            </button>
            {canStart && (
              <button onClick={() => handleStatus("start")} disabled={isActing} className={BTN_SM}>
                <Play size={13} /> {isActing ? "Iniciando…" : "Iniciar"}
              </button>
            )}
            {canStop && (
              <button onClick={() => handleStatus("stop")} disabled={isActing} className={BTN_SM}>
                <Square size={13} /> {isActing ? "Parando…" : "Parar"}
              </button>
            )}
            {canDelete && (
              <button onClick={handleDelete} disabled={isActing} className={BTN_DANGER}>
                <Trash2 size={13} /> Excluir
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
        <div className="mt-4 flex gap-1 border-b border-border">
          {TABS.map((tb) => (
            <button
              key={tb.id}
              onClick={() => setTab(tb.id)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition",
                tab === tb.id
                  ? "border-brand text-brand"
                  : "border-transparent text-fg-3 hover:text-fg-2"
              )}
            >
              {tb.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Conteúdo da aba ── */}
      {tab === "overview" && <OverviewTab instance={instance} metrics={metrics?.metrics ?? {}} />}
      {tab === "backups" && <BackupsTab instance={instance} />}
      {tab === "maintenance" && <MaintenanceTab instance={instance} />}
      {tab === "alerts" && <AlertsTab instance={instance} />}
      {tab === "metrics" && (
        <EmptyState title="Métricas" subtitle="Gráficos entram com métricas-como-série no backend." />
      )}
      {tab === "logs" && (
        <EmptyState title="Logs" subtitle="Sem endpoint de logs por instância ainda." />
      )}
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
  const connActive = metrics.connections_active;
  const connMax = metrics.connections_max;
  const cacheHit = metrics.cache_hit_ratio;
  const sizeBytes = metrics.db_size_bytes;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Conexões"
          value={
            connActive != null
              ? `${Math.round(connActive)}${connMax ? `/${Math.round(connMax)}` : ""}`
              : "—"
          }
          sub="ativas / máx"
        />
        <StatCard
          label="Cache hit"
          value={cacheHit != null ? `${cacheHit.toFixed(1)}%` : "—"}
          sub="meta > 95%"
          accent={cacheHit != null && cacheHit < 95 ? "warn" : "ok"}
        />
        <StatCard label="Tamanho" value={formatBytes(sizeBytes)} sub="banco" />
        <StatCard label="Status" value={instance.status} />
      </div>

      <SlowQueries instance={instance} />
    </div>
  );
}

// ── Tabela de queries lentas (pg_stat_statements) ──
function SlowQueries({ instance }: { instance: Instance }) {
  const [rows, setRows] = useState<SlowQuery[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    // Endpoint exige instância RUNNING; senão nem busca.
    if (instance.status !== "running") {
      setRows([]);
      return;
    }
    getSlowQueries(instance.id)
      .then((r) => setRows(r.queries))
      .catch(() => setUnavailable(true));
  }, [instance.id, instance.status]);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Queries lentas</h2>
        <span className="text-xs text-fg-3">pg_stat_statements</span>
      </div>

      {unavailable ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Indisponível (instância parada ou sem dados).
        </p>
      ) : rows === null ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">Carregando…</p>
      ) : rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-fg-3">
          Sem queries lentas registradas.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">Query</th>
              <th className="px-4 py-2 text-right font-medium">Média</th>
              <th className="px-4 py-2 text-right font-medium">Chamadas</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q, i) => (
              <tr key={i} className="border-t border-border">
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
