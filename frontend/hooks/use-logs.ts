import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { getInstanceLogs } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";

interface UseLogsResult {
  logs: string | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

// Container logs. No automatic polling — the operator refreshes on demand
// (a continuous tail would be costly and noisy in the UI).
export function useLogs(instanceId: string, tail = 200): UseLogsResult {
  const t = useTranslations("Logs");
  const fetcher = useCallback(
    () => getInstanceLogs(instanceId, tail).then((r) => r.logs),
    [instanceId, tail]
  );
  const { data, isLoading, error, refresh } = useResource(
    fetcher,
    t("loadFailed")
  );

  return { logs: data, isLoading, error, refresh };
}
