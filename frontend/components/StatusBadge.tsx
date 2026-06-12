import type { InstanceStatus } from "@/lib/types";

// Mapeia o status real do backend → rótulo em PT + cores do design.
// Usa as cores semânticas com opacidade (ok/info/warn/danger) do globals.css.
const STATUS_MAP: Record<InstanceStatus, { label: string; cls: string }> = {
  running: { label: "Rodando", cls: "text-ok border-ok/25 bg-ok/10" },
  stopped: { label: "Parada", cls: "text-fg-3 border-border bg-bg-2" },
  pending: { label: "Pendente", cls: "text-info border-info/25 bg-info/10" },
  provisioning: { label: "Provisionando", cls: "text-info border-info/25 bg-info/10" },
  deleting: { label: "Removendo", cls: "text-warn border-warn/25 bg-warn/10" },
  deleted: { label: "Removida", cls: "text-fg-3 border-border bg-bg-2" },
  failed: { label: "Falhou", cls: "text-danger border-danger/25 bg-danger/10" },
};

export function StatusBadge({ status }: { status: InstanceStatus }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.stopped;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium ${s.cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {s.label}
    </span>
  );
}

// Badge de SAÚDE (vocabulário do design: Saudável / Pausado / Falhou…), derivada
// do status técnico. Diferente do StatusBadge, que mostra o status cru. Usada nos
// cards do Painel para uma leitura mais "de produto".
//
// Nota honesta: "Degradado" (rodando mas insalubre) exigiria um health check por
// card, que ainda não fazemos no Painel — por isso não inventamos esse estado;
// derivamos só do status já conhecido.
const HEALTH_MAP: Record<InstanceStatus, { label: string; cls: string }> = {
  running: { label: "Saudável", cls: "text-ok border-ok/25 bg-ok/10" },
  stopped: { label: "Pausado", cls: "text-fg-3 border-border bg-bg-2" },
  pending: { label: "Pendente", cls: "text-info border-info/25 bg-info/10" },
  provisioning: { label: "Provisionando", cls: "text-info border-info/25 bg-info/10" },
  deleting: { label: "Removendo", cls: "text-warn border-warn/25 bg-warn/10" },
  deleted: { label: "Removida", cls: "text-fg-3 border-border bg-bg-2" },
  failed: { label: "Falhou", cls: "text-danger border-danger/25 bg-danger/10" },
};

export function HealthBadge({ status }: { status: InstanceStatus }) {
  const s = HEALTH_MAP[status] ?? HEALTH_MAP.stopped;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium ${s.cls}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {s.label}
    </span>
  );
}
