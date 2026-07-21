"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { FlaskConical } from "lucide-react";
import { useSimulation } from "@/hooks/use-simulation";
import { BTN_GHOST } from "@/lib/ui";

// Aviso honesto, sempre visível enquanto houver dado simulado na frota.
//
// Dois estados, e a distinção importa:
//  - rodando: o roteiro está em curso (fase X de N) e há tráfego sendo gerado;
//  - parado, mas com dados: o roteiro acabou (ou foi interrompido) e o que ele
//    semeou continua no banco — o visitante precisa saber disso ao olhar os
//    gráficos, mesmo sem nada acontecendo no momento.
// Frota limpa (nunca simulada) não renderiza nada: a UI não fala de simulação
// para quem não pediu uma.
export function SimulationBanner() {
  const t = useTranslations("Simulation");
  const { status, stop, isPending } = useSimulation();

  if (!status?.enabled) return null;
  if (!status.running && !status.has_simulated_data) return null;

  const running = status.running;
  const phaseLabel = t(`phase.${status.phase}.title`);

  return (
    <div
      role="status"
      className="flex h-9 shrink-0 items-center gap-3 border-b border-warn/25 bg-warn/10 px-5 text-[13px] text-warn"
    >
      <FlaskConical size={14} className="shrink-0" />
      <span className="font-medium">{t("banner.label")}</span>
      <span className="min-w-0 truncate text-warn/80">
        {running
          ? t("banner.running", {
              phase: phaseLabel,
              index: status.phase_index + 1,
              count: status.phase_count,
            })
          : t("banner.finished")}
      </span>

      {running && (
        // Progresso da fase atual — some quando o roteiro termina.
        <div className="h-1 w-24 shrink-0 overflow-hidden rounded-full bg-warn/20">
          <div
            className="h-full rounded-full bg-warn transition-[width] duration-1000 ease-linear"
            style={{ width: `${Math.round(status.phase_progress * 100)}%` }}
          />
        </div>
      )}

      <div className="flex-1" />

      {running && (
        <button type="button" onClick={stop} disabled={isPending} className={BTN_GHOST}>
          {t("actions.stop")}
        </button>
      )}
      <Link href="/demo" className={BTN_GHOST}>
        {t("banner.details")}
      </Link>
    </div>
  );
}
