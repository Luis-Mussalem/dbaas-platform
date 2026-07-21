import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { getFleetSummary } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { InstanceSummary } from "@/lib/types";

// Estado agregado da frota, indexado por id para o card acessar em O(1).
// Uma única requisição serve o grid inteiro — ver getFleetSummary.
//
// O intervalo default acompanha o do card (10s). Durante a simulação de uso a
// página passa o `pollMs` acelerado do SimulationProvider, senão os alertas e
// backups do roteiro só apareceriam no ciclo seguinte.
const POLL_INTERVAL_MS = 10_000;

interface UseFleetSummaryResult {
  summaries: Map<string, InstanceSummary>;
  isLoading: boolean;
  error: string | null;
}

export function useFleetSummary(pollMs?: number, version?: number): UseFleetSummaryResult {
  const t = useTranslations("Dashboard");
  const fetcher = useCallback(() => getFleetSummary(), []);
  const { data, isLoading, error } = useResource(
    fetcher,
    t("loadFailed"),
    pollMs ?? POLL_INTERVAL_MS,
    version
  );

  const summaries = useMemo(
    () => new Map((data?.instances ?? []).map((s) => [s.instance_id, s])),
    [data]
  );

  return { summaries, isLoading, error };
}
