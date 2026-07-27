import type { Environment } from "@/lib/types";

// Single source of truth for environments: canonical backend value
// (production/staging/development) → semantic tone. The displayed label no longer
// lives here: it comes from the messages (Environments.*), translated per locale.
// Consumed by EnvBadge, EnvFilterBar, and the dashboard/instances pages.

export type EnvFilter = "all" | Environment;

export const ENVIRONMENTS: {
  value: Environment;
  tone: "ok" | "warn" | "info";
}[] = [
  { value: "production", tone: "ok" },
  { value: "staging", tone: "warn" },
  { value: "development", tone: "info" },
];

// Segmented filter values, with "all" up front. The labels are built
// in the component (needs a hook to translate).
export const ENV_FILTER_VALUES: EnvFilter[] = ["all", ...ENVIRONMENTS.map((e) => e.value)];

export function environmentTone(env: Environment | null): "ok" | "warn" | "info" | null {
  if (!env) return null;
  return ENVIRONMENTS.find((e) => e.value === env)?.tone ?? null;
}

export function filterByEnvironment<T extends { environment: Environment | null }>(
  items: T[],
  filter: EnvFilter
): T[] {
  return filter === "all" ? items : items.filter((i) => i.environment === filter);
}
