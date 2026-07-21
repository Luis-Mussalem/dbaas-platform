import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getSimulation,
  resetSimulation,
  startSimulation,
  stopSimulation,
} from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { SimulationStatus } from "@/lib/types";

// Enquanto o roteiro corre, o estado muda a cada poucos segundos (fase, log de
// eventos): 3s dá uma UI viva sem inundar o backend. O mesmo hook serve o
// banner global e a página /demo — uma única fonte de verdade.
const POLL_INTERVAL_MS = 3_000;

interface UseSimulationResult {
  status: SimulationStatus | null;
  isLoading: boolean;
  error: string | null;
  isPending: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
}

export function useSimulation(): UseSimulationResult {
  const t = useTranslations("Simulation");
  const fetcher = useCallback(() => getSimulation(), []);
  const { data, isLoading, error, setData } = useResource(
    fetcher,
    t("loadFailed"),
    POLL_INTERVAL_MS
  );
  const [isPending, setIsPending] = useState(false);

  // As três ações devolvem o estado novo — aplicá-lo direto evita o intervalo
  // de até 3s em que o botão pareceria não ter feito nada.
  const run = useCallback(
    async (action: () => Promise<SimulationStatus>) => {
      setIsPending(true);
      try {
        setData(await action());
      } finally {
        setIsPending(false);
      }
    },
    [setData]
  );

  return {
    status: data,
    isLoading,
    error,
    isPending,
    start: useCallback(() => run(startSimulation), [run]),
    stop: useCallback(() => run(stopSimulation), [run]),
    reset: useCallback(() => run(resetSimulation), [run]),
  };
}
