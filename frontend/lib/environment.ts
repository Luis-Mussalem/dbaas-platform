import type { Environment } from "@/lib/types";

// Fonte única de verdade para ambientes: valor canônico do backend
// (production/staging/development) → tom semântico. O rótulo exibido não vive
// mais aqui: vem das mensagens (Environments.*), traduzido por locale.
// Consumido por EnvBadge, EnvFilterBar e as páginas de painel/instâncias.

export type EnvFilter = "all" | Environment;

export const ENVIRONMENTS: {
  value: Environment;
  tone: "ok" | "warn" | "info";
}[] = [
  { value: "production", tone: "ok" },
  { value: "staging", tone: "warn" },
  { value: "development", tone: "info" },
];

// Valores do filtro segmentado, com "all" na frente. Os rótulos são montados
// no componente (precisa de hook para traduzir).
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
