import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { listMaintenanceTasks } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { MaintenanceTask } from "@/lib/types";

// Maintenance history hook, with `refresh` to re-fetch after running a task.
interface UseMaintenanceResult {
  tasks: MaintenanceTask[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useMaintenance(instanceId: string): UseMaintenanceResult {
  const t = useTranslations("Maintenance");
  const fetcher = useCallback(
    () => listMaintenanceTasks(instanceId),
    [instanceId]
  );
  const { data, isLoading, error, refresh } = useResource(fetcher, t("loadFailed"));

  return { tasks: data ?? [], isLoading, error, refresh };
}
