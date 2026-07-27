import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { listBackups } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { Backup } from "@/lib/types";

// Hook for an instance's backup list.
// Exposes `refresh` for the UI to re-fetch after creating/restoring.
interface UseBackupsResult {
  backups: Backup[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useBackups(instanceId: string): UseBackupsResult {
  const t = useTranslations("Backups");
  const fetcher = useCallback(() => listBackups(instanceId), [instanceId]);
  const { data, isLoading, error, refresh } = useResource(fetcher, t("loadFailed"));

  return { backups: data ?? [], isLoading, error, refresh };
}
