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

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { backups, isLoading, error, refresh };
}
