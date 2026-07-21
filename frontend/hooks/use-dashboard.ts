import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { getDashboard } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { DashboardSummary } from "@/lib/types";

// Hook de dados do Painel — busca no mount e expõe { dados, isLoading, error }.
// `pollMs` é usado enquanto a simulação de uso mexe na frota: sem ele, o painel
// só mostrava o resultado depois de um F5.
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
