"use client";

import type { Instance } from "@/lib/types";
import { regionInfo, project, type RegionInfo } from "@/lib/regions";
import { WORLD_LAND_PATH } from "@/lib/world-geo";

// Painel "Mapa de regiões": agrega as instâncias por região e marca cada uma
// sobre um mapa-múndi vetorial real (silhueta dos continentes, Natural Earth).
// O contorno é ilustrativo; os marcadores e a lista trazem os números reais.
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

      {/* Mapa-múndi vetorial (SVG 2:1). Continentes = path; bolhas = regiões. */}
      <div className="mb-3 overflow-hidden rounded-md border border-border bg-bg-2">
        <svg
          viewBox="0 0 360 180"
          className="block w-full"
          role="img"
          aria-label="Mapa-múndi com a distribuição das regiões"
        >
          {/* Silhueta dos continentes */}
          <path
            d={WORLD_LAND_PATH}
            fill="var(--fg-faint)"
            fillOpacity={0.22}
            stroke="var(--fg-3)"
            strokeOpacity={0.3}
            strokeWidth={0.3}
            vectorEffect="non-scaling-stroke"
          />

          {/* Marcadores das regiões com instâncias (anel + ponto) */}
          {rows.map(({ info, count }) => {
            const p = project(info.lat, info.lon);
            return (
              <g key={info.code}>
                <title>{`${info.city} · ${count}`}</title>
                <circle cx={p.x} cy={p.y} r={6} fill="var(--brand)" opacity={0.18} />
                <circle cx={p.x} cy={p.y} r={2.6} fill="var(--brand)" />
              </g>
            );
          })}
        </svg>
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
