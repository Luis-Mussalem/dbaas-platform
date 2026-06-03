import { useCallback, useEffect, useState } from "react";
import { listAlertRules, listAlertEvents } from "@/lib/api";
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
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Promise.all dispara as duas requisições JUNTAS e só resolve quando AMBAS
  // terminam — em vez de esperar uma depois da outra (analogia ao
  // asyncio.gather do Python). Desestruturamos o array na mesma ordem.
  const refresh = useCallback(async () => {
    try {
      const [rulesData, eventsData] = await Promise.all([
        listAlertRules(instanceId),
        listAlertEvents(instanceId, true), // only_open = true
      ]);
      setRules(rulesData);
      setEvents(eventsData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar alertas");
    } finally {
      setIsLoading(false);
    }
  }, [instanceId]);

  // Busca inicial inline (setState dentro do .then/.catch, após o await) — evita
  // o aviso de "setState síncrono no effect". `active` descarta a resposta se o
  // componente desmontar antes dela chegar.
  useEffect(() => {
    let active = true;
    Promise.all([
      listAlertRules(instanceId),
      listAlertEvents(instanceId, true),
    ])
      .then(([rulesData, eventsData]) => {
        if (active) {
          setRules(rulesData);
          setEvents(eventsData);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Falha ao carregar alertas");
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [instanceId]);

  return { rules, events, isLoading, error, refresh };
}
