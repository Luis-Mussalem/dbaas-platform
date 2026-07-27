// Instance IDENTITY color — deterministic, grouped by the region's COUNTRY.
//
// The HUE comes from the country (flag color): Brazil = green, US = blue, Ireland =
// orange, Germany = gold, Singapore = red. The ENVIRONMENT picks the TONE: production
// uses the flag's full color; staging and development use lighter tones
// (mixed toward the theme's surface). Instances of the same country share the
// family and the environment tells them apart.
//
// Why by country, and not by company (a hash of the name): when creating a new company the
// old hash could collide/confuse colors. Anchoring on the country makes the color
// PREDICTABLE — it follows the chosen region, not the name. The same color feeds the avatar,
// the sparkline's line (card), and the region-map markers.
//
// Mid-tone colors chosen to work on both light AND dark themes without changing
// hue. Follows the dataviz guide: a fixed categorical palette per entity (country), with
// secondary reinforcement via the flag + country code (never color alone).

import type { Environment } from "@/lib/types";
import { regionInfo } from "@/lib/regions";

// Country (code) → { fill: base color = the flag's precise tone (production);
//                     ink: text color over that color }.
const COUNTRY_COLORS: Record<string, { fill: string; ink: string }> = {
  BR: { fill: "#007a33", ink: "#ffffff" }, // closed flag green — distinct from the
                                           // theme's emerald green (#10b981), ΔE ~19
  US: { fill: "#2563eb", ink: "#ffffff" }, // visible blue
  IE: { fill: "#ff8200", ink: "#ffffff" }, // orange (Pantone 151)
  DE: { fill: "#f5c518", ink: "#1a1a1a" }, // golden-yellow — pulled toward yellow
                                           // to separate it from Ireland's orange; dark text
  SG: { fill: "#ee2536", ink: "#ffffff" }, // red (Pantone 032)
};

// Unknown country → brand color (same spirit as regionInfo's fallback, which
// never breaks the UI). Since it's a token, it doesn't enter the tones' color-mix.
const FALLBACK = { fill: "var(--brand)", ink: "var(--brand-fg)" };

function colorFor(region: string | null): { fill: string; ink: string } {
  const info = regionInfo(region);
  if (!info) return FALLBACK;
  return COUNTRY_COLORS[info.country] ?? FALLBACK;
}

// Environment → tone: production = full color; staging/undefined = slight lightening;
// development = lighter still. The mix is done with CSS color-mix against the
// current theme's surface, so it lightens in light mode and darkens in dark mode —
// legible in both without changing hue. Brand tokens are not mixed.
function envTone(fill: string, env: Environment | null): string {
  if (fill.startsWith("var(") || env === "production") return fill;
  const surfaceMix = env === "development" ? 34 : 18; // % of surface
  return `color-mix(in oklch, ${fill} ${100 - surfaceMix}%, var(--surface))`;
}

// Avatar gradient: from the environment's tone to a slightly darker version
// (depth). The text uses the country's `ink` (white, or dark over the gold).
export function instanceGradient(region: string | null, env: Environment | null): string {
  const tone = envTone(colorFor(region).fill, env);
  if (tone.startsWith("var(")) return `linear-gradient(135deg, ${tone}, ${tone})`;
  return `linear-gradient(135deg, ${tone}, color-mix(in oklch, ${tone}, black 14%))`;
}

// Solid color of the sparkline's line — same tone as the avatar.
export function instanceLineColor(region: string | null, env: Environment | null): string {
  return envTone(colorFor(region).fill, env);
}

// Color of the initials' text over the avatar (white in most cases; dark over the gold).
export function instanceInk(region: string | null): string {
  return colorFor(region).ink;
}

// Country's solid color (production tone) — used by the region-map markers.
export function countryColor(region: string | null): string {
  return colorFor(region).fill;
}

// Up to 2 initials from the name (e.g.: "checkout-prod" → "CP", "analytics" → "AN").
// The name still defines the INITIALS; only the COLOR now comes from the country.
export function instanceInitials(name: string): string {
  const parts = name.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ").filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (name.trim().slice(0, 2) || "?");
  return letters.toUpperCase();
}
