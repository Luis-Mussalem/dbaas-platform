"use client";

import { useTranslations } from "next-intl";
import {
  Activity,
  CheckCircle2,
  Circle,
  Database,
  FlaskConical,
  Loader2,
  Play,
  RotateCcw,
  Square,
} from "lucide-react";
import { useSimulation } from "@/hooks/use-simulation";
import { useConfirm } from "@/context/ConfirmProvider";
import { useFormatters } from "@/hooks/use-formatters";
import { EmptyState } from "@/components/EmptyState";
import { BTN, BTN_DANGER, BTN_PRIMARY } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { SimulationPhase } from "@/lib/types";

// Ordem do roteiro no backend (services/demo_simulation.py::PHASE_ORDER).
// Duplicada aqui só para desenhar a timeline antes de a simulação começar —
// o estado ao vivo (fase atual, progresso) continua vindo da API.
const PHASES: SimulationPhase[] = [
  "backfill",
  "warmup",
  "alert",
  "backup",
  "maintenance",
  "recover",
  "steady",
];

export default function DemoPage() {
  const t = useTranslations("Simulation");
  const { status, isLoading, isPending, start, stop, reset } = useSimulation();
  const { confirm } = useConfirm();
  const { dateTime } = useFormatters();

  if (isLoading) {
    return <EmptyState title={t("loading")} icon={<Loader2 size={22} className="animate-spin" />} />;
  }

  if (!status?.enabled) {
    return <EmptyState title={t("disabled.title")} subtitle={t("disabled.subtitle")} />;
  }

  const currentIndex = status.running ? status.phase_index : -1;

  async function handleReset() {
    const ok = await confirm({
      title: t("reset.title"),
      description: t("reset.description"),
      confirmText: t("actions.reset"),
      danger: true,
    });
    if (ok) await reset();
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FlaskConical size={20} className="text-brand" />
            {t("title")}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>

        <div className="flex items-center gap-2">
          {status.running ? (
            <button type="button" onClick={stop} disabled={isPending} className={BTN}>
              <Square size={14} />
              {t("actions.stop")}
            </button>
          ) : (
            <button type="button" onClick={start} disabled={isPending} className={BTN_PRIMARY}>
              <Play size={14} />
              {t("actions.start")}
            </button>
          )}
          {status.has_simulated_data && !status.running && (
            <button type="button" onClick={handleReset} disabled={isPending} className={BTN_DANGER}>
              <RotateCcw size={14} />
              {t("actions.reset")}
            </button>
          )}
        </div>
      </header>

      {/* O contrato de honestidade da demo, lado a lado. */}
      <div className="grid gap-3 md:grid-cols-2">
        <section className="rounded-xl border border-border bg-surface p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Database size={15} className="text-ok" />
            {t("real.title")}
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            {t("real.body")}
          </p>
        </section>
        <section className="rounded-xl border border-warn/25 bg-warn/5 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Activity size={15} className="text-warn" />
            {t("seeded.title")}
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            {t("seeded.body")}
          </p>
        </section>
      </div>

      {/* Timeline do roteiro */}
      <section className="rounded-xl border border-border bg-surface p-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">{t("script.title")}</h2>
          <span className="text-xs text-muted-foreground">
            {t("script.speed", { factor: Math.round(status.speed_factor) })}
          </span>
        </div>

        <ol className="mt-3 flex flex-col">
          {PHASES.map((phase, index) => {
            const done = currentIndex > index;
            const active = currentIndex === index;
            return (
              <li key={phase} className="flex gap-3 py-2">
                <div className="flex flex-col items-center">
                  {done ? (
                    <CheckCircle2 size={16} className="text-ok" />
                  ) : active ? (
                    <Loader2 size={16} className="animate-spin text-brand" />
                  ) : (
                    <Circle size={16} className="text-fg-faint" />
                  )}
                  {index < PHASES.length - 1 && (
                    <div className={cn("mt-1 w-px flex-1", done ? "bg-ok/40" : "bg-border")} />
                  )}
                </div>
                <div className="min-w-0 pb-1">
                  <p
                    className={cn(
                      "text-[13px] font-medium",
                      active ? "text-foreground" : done ? "text-fg-2" : "text-muted-foreground"
                    )}
                  >
                    {t(`phase.${phase}.title`)}
                  </p>
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {t(`phase.${phase}.description`)}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* Log do que a simulação fez de fato */}
      {status.events.length > 0 && (
        <section className="rounded-xl border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t("log.title")}</h2>
          <ul className="mt-2 flex flex-col gap-1.5">
            {[...status.events].reverse().map((event, index) => (
              <li key={`${event.at}-${index}`} className="flex gap-3 text-[13px]">
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {dateTime(event.at, "clock")}
                </span>
                <span className="min-w-0 text-fg-2">{event.message}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
