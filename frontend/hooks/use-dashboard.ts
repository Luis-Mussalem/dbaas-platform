import { useCallback } from "react";
import { getDashboard } from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
import type { DashboardSummary } from "@/lib/types";

// Hook de dados do Painel — busca uma vez no mount e expõe { dados, isLoading, error }.
interface UseDashboardResult {
  summary: DashboardSummary | null;
  isLoading: boolean;
  error: string | null;
}

export function useDashboard(): UseDashboardResult {
  const fetcher = useCallback(() => getDashboard(), []);
  const { data, isLoading, error } = useResource(
    fetcher,
    "Falha ao carregar o painel"
  );

  return { summary: data, isLoading, error };
}
