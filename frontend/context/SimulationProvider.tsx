"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import {
  getSimulation,
  resetSimulation,
  startSimulation,
  stopSimulation,
} from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { SimulationStatus } from "@/lib/types";

// Estado da simulação compartilhado por toda a árvore.
//
// Antes cada consumidor (banner, botão da topbar, página /demo) tinha seu
// próprio hook — e portanto seu próprio polling da mesma rota. Como provider,
// há UMA busca a cada 3s, e o dashboard pode usar o mesmo estado para se
// atualizar sozinho enquanto o roteiro corre, em vez de exigir F5.
const POLL_INTERVAL_MS = 3_000;

interface SimulationContextValue {
  status: SimulationStatus | null;
  isLoading: boolean;
  error: string | null;
  isPending: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
  // Intervalo que as telas de dados devem usar para se refrescar: curto
  // enquanto a simulação mexe na frota, ausente quando nada está acontecendo.
  dataPollMs: number | undefined;
}

const SimulationContext = createContext<SimulationContextValue | null>(null);

// Enquanto o roteiro roda, a frota muda a cada poucos segundos (métricas,
// alertas, backups). 5s mantém o dashboard vivo sem martelar a API.
const DATA_POLL_MS = 5_000;

export function SimulationProvider({ children }: { children: ReactNode }) {
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

  const value = useMemo<SimulationContextValue>(
    () => ({
      status: data,
      isLoading,
      error,
      isPending,
      start: () => run(startSimulation),
      stop: () => run(stopSimulation),
      reset: () => run(resetSimulation),
      dataPollMs: data?.running ? DATA_POLL_MS : undefined,
    }),
    [data, isLoading, error, isPending, run]
  );

  return (
    <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>
  );
}

export function useSimulation(): SimulationContextValue {
  const ctx = useContext(SimulationContext);
  if (!ctx) {
    throw new Error("useSimulation must be used inside <SimulationProvider>");
  }
  return ctx;
}
