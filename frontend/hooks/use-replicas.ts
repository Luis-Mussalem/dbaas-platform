import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { listReplicas } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { Replica } from "@/lib/types";

// Lag and streaming state change continuously — the backend poller updates every
// 30s, so we revalidate here at a similar interval to keep the UI in sync.
const POLL_INTERVAL_MS = 15_000;

interface UseReplicasResult {
  replicas: Replica[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useReplicas(instanceId: string): UseReplicasResult {
  const t = useTranslations("Replicas");
  const fetcher = useCallback(() => listReplicas(instanceId), [instanceId]);
  const { data, isLoading, error, refresh } = useResource(
    fetcher,
    t("loadFailed"),
    POLL_INTERVAL_MS
  );

  return { replicas: data ?? [], isLoading, error, refresh };
}
