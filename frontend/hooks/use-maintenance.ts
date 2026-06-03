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

  // Busca inicial inline: o setState acontece DENTRO do .then/.catch (após o
  // await), não no corpo do effect — então não dispara o aviso de "setState
  // síncrono no effect". `active` descarta a resposta se o componente desmontar.
  useEffect(() => {
    let active = true;
    listMaintenanceTasks(instanceId)
      .then((data) => {
        if (active) {
          setTasks(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Falha ao carregar histórico");
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [instanceId]);

  return { tasks, isLoading, error, refresh };
}
