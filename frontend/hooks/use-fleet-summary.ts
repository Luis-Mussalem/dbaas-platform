import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { getFleetSummary } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { InstanceSummary } from "@/lib/types";

// Aggregated fleet state, indexed by id so the card can access it in O(1).
// A single request serves the whole grid — see getFleetSummary.
//
// The default interval matches the card's (10s); callers pass
// DASHBOARD_POLL_MS to match the cadence with the rest of the dashboard.
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
