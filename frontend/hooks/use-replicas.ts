import { useCallback } from "react";
import { listReplicas } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { Replica } from "@/lib/types";

// Lag e estado de streaming mudam continuamente — o poller do backend atualiza a
// cada 30s, então revalidamos aqui num intervalo próximo para a UI acompanhar.
const POLL_INTERVAL_MS = 15_000;

interface UseReplicasResult {
  replicas: Replica[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useReplicas(instanceId: string): UseReplicasResult {
  const fetcher = useCallback(() => listReplicas(instanceId), [instanceId]);
  const { data, isLoading, error, refresh } = useResource(
    fetcher,
    "Falha ao carregar réplicas",
    POLL_INTERVAL_MS
  );

  return { replicas: data ?? [], isLoading, error, refresh };
}
