import type { Environment } from "@/lib/types";

// Tag de ambiente: traduz o valor canônico do backend (production/staging/
// development) para o rótulo PT exibido, com cor semântica. Nulo → não renderiza.
const ENV_MAP: Record<Environment, { label: string; cls: string }> = {
  production: { label: "produção", cls: "text-ok border-ok/25 bg-ok/10" },
  staging: { label: "homologação", cls: "text-warn border-warn/25 bg-warn/10" },
  development: { label: "desenvolvimento", cls: "text-info border-info/25 bg-info/10" },
};

export function EnvBadge({ environment }: { environment: Environment | null }) {
  if (!environment) return null;
  const e = ENV_MAP[environment];
  if (!e) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${e.cls}`}
    >
      {e.label}
    </span>
  );
}
