"use client";

import type { Instance } from "@/lib/types";
import { regionInfo, type RegionInfo } from "@/lib/regions";

// Painel "Mapa de regiões": agrega as instâncias por região e mostra a
// distribuição. O mapa em si é ILUSTRATIVO (pontos posicionados num retângulo
// estilizado, sem biblioteca de geo) — a lista abaixo traz os números reais.
export function RegionMap({ instances }: { instances: Instance[] }) {
  // Agrupa por região (ignora instâncias sem região definida).
  const counts = new Map<string, { info: RegionInfo; count: number }>();
  for (const inst of instances) {
    const info = regionInfo(inst.region);
    if (!info) continue;
    const entry = counts.get(info.code);
    if (entry) entry.count += 1;
    else counts.set(info.code, { info, count: 1 });
  }
  const rows = [...counts.values()].sort((a, b) => b.count - a.count);

  return (
    <div className="rounded-lg border border-border bg-surface p-3.5">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Mapa de regiões</h2>
        <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] text-fg-3">
          ilustrativo
        </span>
      </div>
      <p className="mb-3 text-[11.5px] text-fg-3">Distribuição dos seus bancos</p>

      {/* "mapa" estilizado: retângulo com grade sutil + um ponto por região */}
      <div className="relative mb-3 h-28 overflow-hidden rounded-md border border-border bg-bg-2">
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
            backgroundSize: "16px 16px",
          }}
        />
        {rows.map(({ info, count }) => (
          <div
            key={info.code}
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${info.pos.x}%`, top: `${info.pos.y}%` }}
            title={`${info.city} · ${count}`}
          >
            <span className="block h-2.5 w-2.5 rounded-full bg-brand shadow-[0_0_0_4px_var(--brand-subtle)]" />
          </div>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="py-2 text-center text-xs text-fg-3">Nenhuma região definida.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map(({ info, count }) => (
            <li key={info.code} className="flex items-center gap-2 text-[12.5px]">
              <span className="w-6 text-fg-3">{info.country}</span>
              <span className="flex-1 text-fg-2">{info.city}</span>
              <span className="font-mono tabular-nums text-foreground">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
