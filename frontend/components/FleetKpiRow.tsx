import { StatCard } from "@/components/StatCard";
import { formatBRL, formatNumber } from "@/lib/format";
import type { DashboardSummary } from "@/lib/types";

// Linha de KPIs de performance da frota (Painel + Instâncias).
// Contagem de instâncias/alertas/backups vive na saudação e no cabeçalho da
// lista — aqui ficam as métricas de desempenho e custo, como no design.
// Latência P95 e Uptime exibem "—" enquanto ainda não há dados reais suficientes
// (nunca um zero fabricado).
export function FleetKpiRow({
  summary,
  monthlyCost,
}: {
  summary: DashboardSummary | null;
  monthlyCost: number;
}) {
  const qps = summary?.queries_per_second ?? 0;
  const p95 = summary?.p95_latency_ms;
  const uptime = summary?.fleet_uptime_pct;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard label="Queries/s" value={formatNumber(qps)} sub="transações/s (commits)" />
      <StatCard
        label="Latência P95"
        value={p95 != null ? `${p95.toFixed(0)} ms` : "—"}
        sub="entre queries monitoradas"
      />
      <StatCard label="Gasto mensal" value={formatBRL(monthlyCost)} sub="estimativa por specs" />
      <StatCard
        label="Uptime 30d"
        value={uptime != null ? `${uptime.toFixed(2)}%` : "—"}
        sub={uptime != null ? "últimos 30 dias" : "coletando histórico"}
        accent={uptime != null ? (uptime < 99 ? "warn" : "ok") : "default"}
      />
    </div>
  );
}
