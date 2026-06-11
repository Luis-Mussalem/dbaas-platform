"use client";

import Link from "next/link";
import { Database } from "lucide-react";
import type { Instance } from "@/lib/types";
import { useMetrics } from "@/hooks/use-metrics";
import { useMetricHistory } from "@/hooks/use-metric-history";
import { formatBytes } from "@/lib/format";
import { HealthBadge } from "@/components/StatusBadge";
import { EnvBadge } from "@/components/EnvBadge";
import { RegionTag } from "@/components/RegionTag";
import { Sparkline } from "@/components/Sparkline";

export function InstanceCard({ instance }: { instance: Instance }) {
  // Métricas ao vivo do banco (poll a cada 10s pelo hook). Para instâncias
  // não-RUNNING, o backend devolve a última leitura armazenada (ou vazio).
  const { metrics } = useMetrics(instance.id);
  const m = metrics?.metrics ?? {};

  // Sparkline REAL: histórico de conexões na última hora (vem do endpoint de
  // histórico que lê a tabela metrics). Vazio → o Sparkline mostra uma linha-base.
  const connHistory = useMetricHistory(instance.id, "connections_active", "1h");

  const connActive = m.connections_active;
  const connMax = m.connections_max;
  const cacheHit = m.cache_hit_ratio;
  const sizeBytes = m.db_size_bytes;

  // Barra de armazenamento: tamanho atual do banco vs capacidade contratada.
  const capacityBytes = instance.storage_gb ? instance.storage_gb * 1024 ** 3 : null;
  const storagePct =
    capacityBytes && sizeBytes ? Math.min(100, (sizeBytes / capacityBytes) * 100) : null;

  // Cor do sparkline/saúde segue o status: parada = neutro, falhou = vermelho.
  const sparkColor =
    instance.status === "failed"
      ? "var(--danger)"
      : instance.status === "running"
        ? "var(--brand)"
        : "var(--fg-3)";

  return (
    <Link
      href={`/instances/${instance.id}`}
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
    >
      {/* topo: ícone + nome + região  ·  saúde */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-linear-to-br from-primary to-info text-primary-foreground">
            <Database size={16} />
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

      {/* ambiente (tag) */}
      {instance.environment && (
        <div>
          <EnvBadge environment={instance.environment} />
        </div>
      )}

      {/* sparkline real: conexões na última hora */}
      <Sparkline data={connHistory} color={sparkColor} className="h-12 w-full" />

      {/* métricas ao vivo */}
      <div className="flex items-center justify-between">
        <Metric
          label="conexões"
          value={
            connActive != null
              ? `${Math.round(connActive)}${connMax ? `/${Math.round(connMax)}` : ""}`
              : "—"
          }
        />
        <Metric
          label="cache hit"
          value={cacheHit != null ? `${cacheHit.toFixed(1)}%` : "—"}
          align="right"
        />
        <Metric label="tamanho" value={formatBytes(sizeBytes)} align="right" />
      </div>

      {/* armazenamento */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-fg-3">
          <span>Armazenamento</span>
          <span className="font-mono text-fg-2">
            {storagePct != null
              ? `${storagePct.toFixed(0)}%`
              : instance.storage_gb
                ? `${instance.storage_gb} GB`
                : "—"}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-bg-2">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${storagePct ?? 0}%`,
              backgroundColor: (storagePct ?? 0) > 85 ? "var(--warn)" : "var(--brand)",
            }}
          />
        </div>
      </div>
    </Link>
  );
}

function Metric({
  label,
  value,
  align = "left",
}: {
  label: string;
  value: string;
  align?: "left" | "right";
}) {
  return (
    <div className={align === "right" ? "text-right" : ""}>
      <div className="font-mono text-base font-semibold tabular-nums">{value}</div>
      <div className="text-[11.5px] text-fg-3">{label}</div>
    </div>
  );
}
