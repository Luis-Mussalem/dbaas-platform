import { useCallback, useEffect, useState } from "react";
import { listBackups } from "@/lib/api";
import type { Backup } from "@/lib/types";

// Hook da lista de backups de uma instância.
// Expõe `refresh` para a UI re-buscar após criar/restaurar.
interface UseBackupsResult {
  backups: Backup[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useBackups(instanceId: string): UseBackupsResult {
  const [backups, setBackups] = useState<Backup[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listBackups(instanceId);
      setBackups(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar backups");
    } finally {
      setIsLoading(false);
    }
  }, [instanceId]);

  // Busca inicial inline (setState dentro do .then/.catch, após o await) — evita
  // o aviso de "setState síncrono no effect". `active` descarta a resposta se o
  // componente desmontar antes dela chegar.
  useEffect(() => {
    let active = true;
    listBackups(instanceId)
      .then((data) => {
        if (active) {
          setBackups(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Falha ao carregar backups");
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [instanceId]);

  return { backups, isLoading, error, refresh };
}
