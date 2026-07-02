import type { Environment } from "@/lib/types";
import { ENVIRONMENTS } from "@/lib/environment";

// Tag de ambiente: rótulo PT + cor semântica, derivados da fonte única
// lib/environment. Só as classes Tailwind do tom moram aqui (o resto é
// compartilhado). Ambiente nulo → não renderiza.
const TONE_CLS: Record<"ok" | "warn" | "info", string> = {
  ok: "text-ok border-ok/25 bg-ok/10",
  warn: "text-warn border-warn/25 bg-warn/10",
  info: "text-info border-info/25 bg-info/10",
};

export function EnvBadge({ environment }: { environment: Environment | null }) {
  if (!environment) return null;
  const e = ENVIRONMENTS.find((x) => x.value === environment);
  if (!e) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE_CLS[e.tone]}`}
    >
      {e.label}
    </span>
  );
}
