"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import type { Instance } from "@/lib/types";
import { useMetrics } from "@/hooks/use-metrics";
import { useMetricHistory } from "@/hooks/use-metric-history";
import { useSimulation } from "@/context/SimulationProvider";
import { useFormatters } from "@/hooks/use-formatters";
import { instanceGradient, instanceInitials, instanceLineColor, instanceInk } from "@/lib/identity-color";
import { HealthBadge } from "@/components/StatusBadge";
import { EnvBadge } from "@/components/EnvBadge";
import { RegionTag } from "@/components/RegionTag";
import { Sparkline } from "@/components/Sparkline";

export function InstanceCard({ instance }: { instance: Instance }) {
  const t = useTranslations("InstanceCard");
  const tc = useTranslations("Common");
  const { bytes, ratio } = useFormatters();
  // Métricas ao vivo do banco (poll a cada 10s pelo hook). Para instâncias
  // não-RUNNING, o backend devolve a última leitura armazenada (ou vazio).
  const { metrics } = useMetrics(instance.id);
  const m = metrics?.metrics ?? {};

  // Sparkline REAL: histórico de conexões nas últimas 24h (vem do endpoint de
  // histórico que lê a tabela metrics). Vazio → o Sparkline mostra uma linha-base.
  const { dataPollMs } = useSimulation();
  // 48 baldes de 30 min para 24h: um sparkline de ~250px não mostra mais que
  // isso, e a média por balde é o que mantém a linha suave independentemente da
  // cadência de coleta (que acelera durante a simulação de uso).
  const connHistory = useMetricHistory(
    instance.id,
    "connections_active",
    "24h",
    dataPollMs,
    48
  );

  const connActive = m.connections_active;
  const connMax = m.connections_max;
  const cacheHit = m.cache_hit_ratio;
  const sizeBytes = m.db_size_bytes;

  // Barra de armazenamento: tamanho atual do banco vs capacidade contratada.
  const capacityBytes = instance.storage_gb ? instance.storage_gb * 1024 ** 3 : null;
  const storagePct =
    capacityBytes && sizeBytes ? Math.min(100, (sizeBytes / capacityBytes) * 100) : null;

  // A linha do sparkline usa a cor de IDENTIDADE do país (mesma do avatar),
  // exceto quando falhou — aí o vermelho de status prevalece como sinal forte.
  const sparkColor =
    instance.status === "failed"
      ? "var(--danger)"
      : instanceLineColor(instance.region, instance.environment);

  return (
    <Link
      href={`/instances/${instance.id}`}
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 transition hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
    >
      {/* topo: ícone + nome + região  ·  saúde */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* avatar com cor de identidade do PAÍS (matiz) + tom pelo ambiente */}
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
          label={t("connections")}
          value={
            connActive != null
              ? `${Math.round(connActive)}${connMax ? `/${Math.round(connMax)}` : ""}`
              : tc("none")
          }
        />
        <Metric
          label={t("cacheHit")}
          value={cacheHit != null ? `${ratio(cacheHit)}%` : tc("none")}
          align="right"
        />
        <Metric label={t("size")} value={bytes(sizeBytes)} align="right" />
      </div>

      {/* armazenamento */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-fg-3">
          <span>{t("storage")}</span>
          <span className="font-mono text-fg-2">
            {storagePct != null
              ? `${Math.round(storagePct)}%`
              : instance.storage_gb
                ? `${instance.storage_gb} GB`
                : tc("none")}
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
