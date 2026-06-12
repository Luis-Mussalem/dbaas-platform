import { regionInfo } from "@/lib/regions";

// Tag de região: flag + cidade. Usada no card e no cabeçalho da instância.
// Nulo → não renderiza (instância sem região definida).
export function RegionTag({ region }: { region: string | null }) {
  const info = regionInfo(region);
  if (!info) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[11.5px] text-fg-3">
      <span aria-hidden>{info.flag}</span>
      {info.city}
    </span>
  );
}
