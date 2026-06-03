import { useCallback, useEffect, useState } from "react";
import { listMaintenanceTasks } from "@/lib/api";
import type { MaintenanceTask } from "@/lib/types";

// Hook do histórico de manutenção, com `refresh` para re-buscar após executar.
interface UseMaintenanceResult {
  tasks: MaintenanceTask[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMaintenance(instanceId: string): UseMaintenanceResult {
  const [tasks, setTasks] = useState<MaintenanceTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listMaintenanceTasks(instanceId);
      setTasks(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar histórico");
    } finally {
      setIsLoading(false);
    }
  }, [instanceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { tasks, isLoading, error, refresh };
}
