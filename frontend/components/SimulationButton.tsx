"use client";

import { useTranslations } from "next-intl";
import { FlaskConical, Square } from "lucide-react";
import { useSimulation } from "@/context/SimulationProvider";

// Atalho da simulação na topbar, ao lado de "Nova instância" — sem ele, quem
// nunca abrisse a rota /demo jamais descobriria o principal recurso da demo.
//
// O rótulo alterna (Simular uso ↔ Parar) mas a POSIÇÃO não: o controle nunca
// muda de lugar debaixo do cursor. Compartilha o useSimulation() com o banner,
// então os dois refletem o mesmo estado sem uma requisição a mais.
export function SimulationButton() {
  const t = useTranslations("Simulation");
  const { status, start, stop, isPending } = useSimulation();

  // Instalação sem DEMO_MODE (ou estado ainda carregando): nada a mostrar.
  if (!status?.enabled) return null;

  const running = status.running;

  return (
    <button
      type="button"
      onClick={running ? stop : start}
      disabled={isPending}
      title={running ? t("actions.stop") : t("actions.start")}
      className="flex h-9 items-center gap-2 rounded-md border border-brand/30 bg-brand-subtle px-3.5 text-[15px] font-medium text-brand transition hover:bg-brand/15 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {running ? <Square size={16} /> : <FlaskConical size={17} />}
      <span className="hidden lg:inline">
        {running ? t("actions.stop") : t("actions.start")}
      </span>
    </button>
  );
}
