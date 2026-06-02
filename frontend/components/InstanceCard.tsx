"use client";

import Link from "next/link";
import { Database } from "lucide-react";
import type { Instance } from "@/lib/types";
import { useMetrics } from "@/hooks/use-metrics";
import { formatBytes } from "@/lib/format";
import { StatusBadge } from "@/components/StatusBadge";

export function InstanceCard({ instance }: { instance: Instance }) {
  // Métricas ao vivo do banco (poll a cada 10s pelo hook). Para instâncias
  // não-RUNNING, o backend devolve a última leitura armazenada (ou vazio).
  const { metrics } = useMetrics(instance.id);
  const m = metrics?.metrics ?? {};

  const connActive = m.connections_active;
  const connMax = m.connections_max;
  const cacheHit = m.cache_hit_ratio;
  const sizeBytes = m.db_size_bytes;

  // Barra de armazenamento: tamanho atual do banco vs capacidade contratada.
  const capacityBytes = instance.storage_gb ? instance.storage_gb * 1024 ** 3 : null;
  const storagePct =
    capacityBytes && sizeBytes ? Math.min(100, (sizeBytes / capacityBytes) * 100) : null;

  return (
    <Link
      href={`/instances/${instance.id}`}
      className="flex flex-col gap-3.5 rounded-xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
    >
      {/* topo: nome + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-linear-to-br from-primary to-info text-primary-foreground">
            <Database size={16} />
          </div>
          <div>
            <div className="text-[14.5px] font-semibold text-foreground">{instance.name}</div>
            <div className="text-xs text-fg-3">PostgreSQL {instance.engine_version}</div>
          </div>
        </div>
        <StatusBadge status={instance.status} />
      </div>

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
