"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { MetricsSnapshot } from "@/lib/types";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface MetricsChartProps {
  snapshot: MetricsSnapshot;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function MetricsChart({ snapshot }: MetricsChartProps) {
  // recharts expects an array: [{ name: string, value: number }, ...]
  // Our data is an object: { cache_hit_ratio: 0.99, active_connections: 5, ... }
  // Object.entries() converts: { a: 1, b: 2 } → [["a", 1], ["b", 2]]
  // Then .map() transforms each pair into the shape recharts needs.
  //
  // We skip metrics > 1_000_000 (raw byte sizes) — they destroy the Y-axis scale
  // when mixed with small values like connection counts or ratios.
  const data = Object.entries(snapshot.metrics)
    .filter(([, value]) => value < 1_000_000)
    .map(([key, value]) => ({
      name: key.replace(/_/g, " "),        // "cache_hit_ratio" → "cache hit ratio"
      value: Number(value.toFixed(2)),      // 0.997341 → 1 (toFixed returns string, Number converts back)
    }));

  if (data.length === 0) return null;

  return (
    // ResponsiveContainer: fills 100% of parent width, fixed height
    // Without it, BarChart would need explicit pixel width
    <div className="px-4 pt-2 pb-4">
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -8, bottom: 48 }}>
          {/* XAxis: reads the "name" field from each data item */}
          <XAxis
            dataKey="name"
            tick={{ fill: "#71717a", fontSize: 11 }}
            angle={-25}
            textAnchor="end"
            interval={0}
          />
          {/* YAxis: auto-scales to the max value in data */}
          <YAxis tick={{ fill: "#71717a", fontSize: 11 }} width={40} />
          {/* Tooltip: shows value on hover — styled to match dark theme */}
          <Tooltip
            contentStyle={{
              backgroundColor: "#18181b",
              border: "1px solid #3f3f46",
              borderRadius: "6px",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#a1a1aa" }}
            itemStyle={{ color: "#e4e4e7" }}
          />
          {/* Bar: reads the "value" field; radius rounds the top corners */}
          <Bar dataKey="value" fill="#52525b" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}