import type { Environment } from "@/lib/types";

// Fonte única de verdade para ambientes: valor canônico do backend
// (production/staging/development) → rótulo PT exibido + tom semântico.
// Consumido por EnvBadge, EnvFilterBar e as páginas de painel/instâncias —
// evita duplicar o mapa em cada lugar.

export type EnvFilter = "all" | Environment;

export const ENVIRONMENTS: {
  value: Environment;
  label: string;
  tone: "ok" | "warn" | "info";
}[] = [
  { value: "production", label: "produção", tone: "ok" },
  { value: "staging", label: "homologação", tone: "warn" },
  { value: "development", label: "desenvolvimento", tone: "info" },
];

// Opções do filtro segmentado, com "Todos" na frente.
export const ENV_FILTERS: { value: EnvFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  ...ENVIRONMENTS.map((e) => ({ value: e.value, label: e.label })),
];

export function environmentLabel(env: Environment | null): string | null {
  if (!env) return null;
  return ENVIRONMENTS.find((e) => e.value === env)?.label ?? null;
}

export function filterByEnvironment<T extends { environment: Environment | null }>(
  items: T[],
  filter: EnvFilter
): T[] {
  return filter === "all" ? items : items.filter((i) => i.environment === filter);
}
