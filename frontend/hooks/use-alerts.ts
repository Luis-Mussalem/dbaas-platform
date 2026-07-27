import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { listAlertRules, listAlertEvents } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { AlertRule, AlertEvent } from "@/lib/types";

// Hook that brings together the TWO sources of the alerts tab: the configured rules and the
// open events (fired and not yet resolved). `refresh` re-fetches both
// after creating/deleting a rule, seeding defaults, or resolving an event.
interface UseAlertsResult {
  rules: AlertRule[];
  events: AlertEvent[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useAlerts(instanceId: string): UseAlertsResult {
  const t = useTranslations("Alerts");
  // Promise.all fires both requests TOGETHER and only resolves once BOTH
  // finish (analogous to Python's asyncio.gather). The fetcher returns the two
  // lists in a single object so useResource treats them as one single resource.
  const fetcher = useCallback(async () => {
    const [rules, events] = await Promise.all([
      listAlertRules(instanceId),
      listAlertEvents(instanceId, true), // only_open = true
    ]);
    return { rules, events };
  }, [instanceId]);

  const { data, isLoading, error, refresh } = useResource(fetcher, t("loadFailed"));

  return {
    rules: data?.rules ?? [],
    events: data?.events ?? [],
    isLoading,
    error,
    refresh,
  };
}
