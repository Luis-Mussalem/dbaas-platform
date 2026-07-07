import { useCallback } from "react";
import { listAlertRules, listAlertEvents } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { AlertRule, AlertEvent } from "@/lib/types";

// Hook que reúne as DUAS fontes da aba de alertas: as regras configuradas e os
// eventos em aberto (disparados e ainda não resolvidos). `refresh` re-busca as
// duas após criar/excluir regra, semear padrões ou resolver um evento.
interface UseAlertsResult {
  rules: AlertRule[];
  events: AlertEvent[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useAlerts(instanceId: string): UseAlertsResult {
  // Promise.all dispara as duas requisições JUNTAS e só resolve quando AMBAS
  // terminam (analogia ao asyncio.gather do Python). O fetcher devolve as duas
  // listas num objeto único para o useResource tratar como um recurso só.
  const fetcher = useCallback(async () => {
    const [rules, events] = await Promise.all([
      listAlertRules(instanceId),
      listAlertEvents(instanceId, true), // only_open = true
    ]);
    return { rules, events };
  }, [instanceId]);

  const { data, isLoading, error, refresh } = useResource(
    fetcher,
    "Falha ao carregar alertas"
  );

  return {
    rules: data?.rules ?? [],
    events: data?.events ?? [],
    isLoading,
    error,
    refresh,
  };
}
