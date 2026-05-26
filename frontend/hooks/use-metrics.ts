import { useEffect, useState } from "react";
import { getMetrics } from "@/lib/api";
import type { MetricsSnapshot } from "@/lib/types";

const POLL_INTERVAL_MS = 10_000;

interface UseMetricsResult {
  metrics: MetricsSnapshot | null;
  isLoading: boolean;
  error: string | null;
}

export function useMetrics(instanceId: string): UseMetricsResult {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function fetchMetrics() {
      getMetrics(instanceId)
        .then(setMetrics)
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Failed to load metrics")
        )
        .finally(() => setIsLoading(false));
    }

    fetchMetrics();

    const intervalId = setInterval(fetchMetrics, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [instanceId]);

  return { metrics, isLoading, error };
}