"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { TriangleAlert, DatabaseBackup, ShieldCheck } from "lucide-react";
import type { Instance, InstanceSummary } from "@/lib/types";
import { useMetricHistory } from "@/hooks/use-metric-history";
import { useSimulation } from "@/context/SimulationProvider";
import { useFormatters } from "@/hooks/use-formatters";
import { instanceGradient, instanceInitials, instanceLineColor, instanceInk } from "@/lib/identity-color";
import { HealthBadge } from "@/components/StatusBadge";
import { EnvBadge } from "@/components/EnvBadge";
import { RegionTag } from "@/components/RegionTag";
import { Sparkline } from "@/components/Sparkline";

// Largura mínima da barra de storage, em %. Um banco pequeno num plano grande
// dá uma fração de 1%: sem piso, a barra some e o card sugere "sem dados"
// quando na verdade a leitura é boa.
const MIN_BAR_PCT = 1.5;

export function InstanceCard({
  instance,
  summary,
}: {
  instance: Instance;
  // Ausente enquanto o agregado da frota carrega — o card renderiza sem ele.
  summary?: InstanceSummary;
}) {
  const t = useTranslations("InstanceCard");
  const tc = useTranslations("Common");
  const { bytes, ratio, number, ago } = useFormatters();

  // Sparkline REAL: histórico de conexões nas últimas 24h (vem do endpoint de
  // histórico que lê a tabela metrics). Vazio → o Sparkline mostra uma linha-base.
  const { dataPollMs, dataVersion } = useSimulation();
  // Janela de 1h em 60 baldes — um balde por minuto, que é a cadência do poller
  // em repouso. Antes eram 24h em 48 baldes de 30 min: cada amostra nova movia
  // a média do último balde em ~1/30, então a linha parecia CONGELADA mesmo com
  // o polling funcionando. O card mostra o presente; a visão de 24h continua na
  // tela de detalhe, onde há espaço para lê-la.
  const connHistory = useMetricHistory(
    instance.id,
    "connections_active",
    "1h",
    dataPollMs,
    60,
    dataVersion
  );

  // Todos os valores escalares vêm do agregado da frota: uma requisição serve
  // o grid inteiro, em vez de um GET /metrics por card a cada poll.
  const connActive = summary?.connections_active;
  const connMax = summary?.connections_max;
  const sizeBytes = summary?.db_size_bytes;

  // Barra de armazenamento: tamanho atual do banco vs capacidade contratada.
  const capacityBytes = instance.storage_gb ? instance.storage_gb * 1024 ** 3 : null;
  const storagePct =
    capacityBytes && sizeBytes ? Math.min(100, (sizeBytes / capacityBytes) * 100) : null;

  const growth = summary?.size_delta_24h_bytes;
  const growthDirection = growth == null || growth === 0 ? "flat" : growth > 0 ? "up" : "down";

  // A linha do sparkline usa a cor de IDENTIDADE do país (mesma do avatar),
  // exceto quando falhou — aí o vermelho de status prevalece como sinal forte.
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

      {/* ambiente (tag) · alertas abertos */}
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

      {/* sparkline real: conexões nas últimas 24h */}
      <Sparkline data={connHistory} color={sparkColor} className="h-12 w-full" />

      {/* métricas ao vivo: as três que se movem com a carga */}
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
              ? number(Math.round(summary.queries_per_second))
              : tc("none")
          }
          align="right"
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

      {/* armazenamento: usado / plano, com o crescimento das últimas 24h */}
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

      {/* rodapé: sinais de operação — o que um DBA olha antes de abrir a instância */}
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
