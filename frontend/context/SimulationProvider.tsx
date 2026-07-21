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
  // enquanto a simulação mexe na frota, de fundo quando ela não está rodando.
  dataPollMs: number;
  // Muda a cada start/stop/reset. As telas de dados o incluem nas dependências
  // do efeito de busca para refazer a leitura NA HORA, sem esperar o próximo
  // intervalo. Sem isto, um reset com a simulação já parada não mudava nada
  // observável no contexto (o intervalo continuava 30s), e o dashboard ficava
  // até meio minuto mostrando o estado antigo — ou vazio, logo após o reset.
  dataVersion: number;
}

const SimulationContext = createContext<SimulationContextValue | null>(null);

// Enquanto o roteiro roda, a frota muda a cada poucos segundos (métricas,
// alertas, backups). 5s mantém o dashboard vivo sem martelar a API.
const RUNNING_DATA_POLL_MS = 5_000;

// Cadência de fundo, fora do roteiro. Antes o intervalo simplesmente sumia
// quando a simulação parava, e as telas congelavam até um F5 — mas a frota
// continua viva: os containers servem tráfego e o poller coleta a cada 60s.
// 30s é metade do período de coleta, então nenhuma amostra fica visível por
// mais de meio ciclo depois de existir.
const IDLE_DATA_POLL_MS = 30_000;

export function SimulationProvider({ children }: { children: ReactNode }) {
  const t = useTranslations("Simulation");
  const fetcher = useCallback(() => getSimulation(), []);
  const { data, isLoading, error, setData } = useResource(
    fetcher,
    t("loadFailed"),
    POLL_INTERVAL_MS
  );
  const [isPending, setIsPending] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);

  // As três ações devolvem o estado novo — aplicá-lo direto evita o intervalo
  // de até 3s em que o botão pareceria não ter feito nada.
  const run = useCallback(
    async (action: () => Promise<SimulationStatus>) => {
      setIsPending(true);
      try {
        setData(await action());
        setDataVersion((v) => v + 1);
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
      dataPollMs: data?.running ? RUNNING_DATA_POLL_MS : IDLE_DATA_POLL_MS,
      dataVersion,
    }),
    [data, isLoading, error, isPending, run, dataVersion]
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
