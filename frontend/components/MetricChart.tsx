"use client";

import {
  Area,
  AreaChart,
  Line,
  LineChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// Ponto genérico de série temporal já formatado para o gráfico.
export interface ChartPoint {
  t: string; // rótulo do eixo X (ex.: "14:30")
  [series: string]: string | number;
}

const AXIS = { fill: "var(--fg-3)", fontSize: 11 };
const TOOLTIP = {
  contentStyle: {
    backgroundColor: "var(--surface)",
    border: "1px solid var(--border-strong)",
    borderRadius: "8px",
    fontSize: "12px",
  },
  labelStyle: { color: "var(--fg-3)" },
  itemStyle: { color: "var(--fg)" },
};

// Gráfico de ÁREA para uma única métrica (ex.: conexões ao longo do tempo).
export function MetricArea({
  data,
  color = "#34d399",
  height = 200,
}: {
  data: ChartPoint[];
  color?: string;
  height?: number;
}) {
  const gid = `area-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={28} />
        <YAxis tick={AXIS} width={40} />
        <Tooltip {...TOOLTIP} />
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.6}
          fill={`url(#${gid})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Gráfico de LINHAS para múltiplas séries (ex.: latência p50/p95/p99).
export function MultiLineChart({
  data,
  series,
  height = 200,
}: {
  data: ChartPoint[];
  series: { key: string; color: string }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <XAxis dataKey="t" tick={AXIS} interval="preserveStartEnd" minTickGap={28} />
        <YAxis tick={AXIS} width={40} />
        <Tooltip {...TOOLTIP} />
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stroke={s.color}
            strokeWidth={1.6}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
