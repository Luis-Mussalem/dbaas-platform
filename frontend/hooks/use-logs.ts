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

// Logs do container. Sem polling automático — o operador atualiza sob demanda
// (um tail contínuo seria custoso e ruidoso na UI).
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
