import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { listBackups } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
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
  const t = useTranslations("Backups");
  const fetcher = useCallback(() => listBackups(instanceId), [instanceId]);
  const { data, isLoading, error, refresh } = useResource(fetcher, t("loadFailed"));

  return { backups: data ?? [], isLoading, error, refresh };
}
