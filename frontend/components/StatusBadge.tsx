"use client";

import { useTranslations } from "next-intl";
import type { InstanceStatus } from "@/lib/types";

// Cores do design por status (semânticas ok/info/warn/danger do globals.css).
// Os rótulos vivem nas mensagens: Status.* (status técnico cru) e Health.*
// (vocabulário de produto) — mesmas chaves, redações diferentes por locale.
const STATUS_CLS: Record<InstanceStatus, string> = {
  running: "text-ok border-ok/25 bg-ok/10",
  stopped: "text-fg-3 border-border bg-bg-2",
  pending: "text-info border-info/25 bg-info/10",
  provisioning: "text-info border-info/25 bg-info/10",
  deleting: "text-warn border-warn/25 bg-warn/10",
  deleted: "text-fg-3 border-border bg-bg-2",
  failed: "text-danger border-danger/25 bg-danger/10",
};

const BADGE =
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium";

export function StatusBadge({ status }: { status: InstanceStatus }) {
  const t = useTranslations("Status");
  const cls = STATUS_CLS[status] ?? STATUS_CLS.stopped;
  return (
    <span className={`${BADGE} ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(status)}
    </span>
  );
}

// Badge de SAÚDE (Saudável / Pausado / Falhou…), derivada do status técnico.
// Diferente do StatusBadge, que mostra o status cru. Usada nos cards do Painel
// para uma leitura mais "de produto".
//
// Nota honesta: "Degradado" (rodando mas insalubre) exigiria um health check por
// card, que ainda não fazemos no Painel — por isso não inventamos esse estado;
// derivamos só do status já conhecido. Daí Health.* reusar as chaves de status.
export function HealthBadge({ status }: { status: InstanceStatus }) {
  const t = useTranslations("Health");
  const cls = STATUS_CLS[status] ?? STATUS_CLS.stopped;
  return (
    <span className={`${BADGE} ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(status)}
    </span>
  );
}
