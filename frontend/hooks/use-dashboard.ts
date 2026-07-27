import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { getDashboard } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { DashboardSummary } from "@/lib/types";

// Dashboard data hook — fetches on mount and exposes { summary, isLoading, error }.
// `pollMs` is used while the usage simulation touches the fleet: without it, the dashboard
// would only show the result after an F5.
interface UseDashboardResult {
  summary: DashboardSummary | null;
  isLoading: boolean;
  error: string | null;
}

export function useDashboard(pollMs?: number, version?: number): UseDashboardResult {
  const t = useTranslations("Dashboard");
  const fetcher = useCallback(() => getDashboard(), []);
  const { data, isLoading, error } = useResource(
    fetcher,
    t("loadFailed"),
    pollMs,
    version
  );

  return { summary: data, isLoading, error };
}
