import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { getMetrics } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { MetricsSnapshot } from "@/lib/types";

const POLL_INTERVAL_MS = 10_000;

interface UseMetricsResult {
  metrics: MetricsSnapshot | null;
  isLoading: boolean;
  error: string | null;
}

export function useMetrics(instanceId: string): UseMetricsResult {
  const t = useTranslations("Metrics");
  const fetcher = useCallback(() => getMetrics(instanceId), [instanceId]);
  const { data, isLoading, error } = useResource(
    fetcher,
    t("loadFailed"),
    POLL_INTERVAL_MS
  );

  return { metrics: data, isLoading, error };
}
