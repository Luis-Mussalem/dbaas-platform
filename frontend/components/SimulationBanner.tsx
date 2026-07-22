"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { FlaskConical } from "lucide-react";
import { useSimulation } from "@/context/SimulationProvider";
import { BTN_GHOST } from "@/lib/ui";

// Aviso mostrado só enquanto uma demo ao vivo roda.
//
// A frota já nasce semeada (has_simulated_data é sempre True), então dirigir o
// banner por esse sinal o deixaria permanente — o que não faz sentido: a base
// populada é o estado NORMAL da demo, não uma exceção a avisar. Dois estados:
//  - roteiro em curso: mostra a etapa (X de N) e o progresso dela;
//  - regime (steady): o roteiro acabou, o tráfego segue na base — sem barra de
//    progresso, senão parece que ainda está carregando algo.
// A divulgação "dado de demonstração" fica estática na página /demo e no README.
export function SimulationBanner() {
  const t = useTranslations("Simulation");
  const { status, stop, isPending } = useSimulation();

  if (!status?.enabled) return null;
  if (!status.running) return null;

  const running = status.running;
  const complete = status.phase === "steady";
  const inScript = running && !complete;

  return (
    <div
      role="status"
      className="flex h-11 shrink-0 items-center gap-3.5 border-b border-warn/25 bg-warn/10 px-6 text-[15px] text-warn"
    >
      <FlaskConical size={17} className="shrink-0" />
      <span className="font-medium">{t("banner.label")}</span>
      <span className="min-w-0 truncate text-warn/80">
        {inScript
          ? t("banner.running", {
              phase: t(`phase.${status.phase}.title`),
              index: status.phase_index + 1,
              count: status.phase_count,
            })
          : t("banner.complete")}
      </span>

      {inScript && (
        // Expectativa de duração: sem ela, um visitante que clicou não sabe se
        // espera 10 segundos ou cinco minutos.
        <span className="hidden shrink-0 text-warn/70 lg:inline">
          · {t("banner.eta")}
        </span>
      )}

      {inScript && (
        // Progresso do ROTEIRO, não da etapa: a barra por etapa zerava a cada
        // transição e parecia andar de ré. Em regime ela some, de propósito.
        <div className="h-1.5 w-28 shrink-0 overflow-hidden rounded-full bg-warn/20">
          <div
            className="h-full rounded-full bg-warn transition-[width] duration-1000 ease-linear"
            style={{ width: `${Math.round(status.progress * 100)}%` }}
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
