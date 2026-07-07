import { useCallback } from "react";
import { listMaintenanceTasks } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { MaintenanceTask } from "@/lib/types";

// Hook do histórico de manutenção, com `refresh` para re-buscar após executar.
interface UseMaintenanceResult {
  tasks: MaintenanceTask[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMaintenance(instanceId: string): UseMaintenanceResult {
  const fetcher = useCallback(
    () => listMaintenanceTasks(instanceId),
    [instanceId]
  );
  const { data, isLoading, error, refresh } = useResource(
    fetcher,
    "Falha ao carregar histórico"
  );

  return { tasks: data ?? [], isLoading, error, refresh };
}
