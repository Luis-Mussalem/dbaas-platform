import { regionInfo } from "@/lib/regions";

// Region tag: flag + city. Used in the card and in the instance's header.
// Null → renders nothing (instance with no region set).
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
