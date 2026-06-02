import { useEffect, useState } from "react";
import { getDashboard } from "@/lib/api";
import type { DashboardSummary } from "@/lib/types";

// Hook de dados do Painel — mesmo padrão de use-instances:
// busca uma vez no mount e expõe { dados, isLoading, error }.
interface UseDashboardResult {
  summary: DashboardSummary | null;
  isLoading: boolean;
  error: string | null;
}

export function useDashboard(): UseDashboardResult {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setSummary)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Falha ao carregar o painel")
      )
      .finally(() => setIsLoading(false));
  }, []);

  return { summary, isLoading, error };
}
