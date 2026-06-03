import { useCallback, useEffect, useState } from "react";
import { getAuditLogs } from "@/lib/api";
import type { AuditLog } from "@/lib/types";

// Quantos registros buscar por página. Se a resposta vier com exatamente esse
// tamanho, assumimos que PODE haver mais (habilita o "Carregar mais").
const PAGE_SIZE = 20;

interface AuditFilters {
  action?: string;
  resource_type?: string;
}

interface UseAuditResult {
  logs: AuditLog[];
  isLoading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => Promise<void>;
}

// Paginação por offset/limit ACUMULANDO: diferente das outras hooks (que
// substituem a lista a cada busca), aqui a primeira página substitui e as
// seguintes são CONCATENADAS no fim (setLogs(prev => [...prev, ...data])).
// Mudar qualquer filtro reseta tudo para a página 0.
export function useAudit(filters: AuditFilters): UseAuditResult {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  // Primeira página (e reset quando um filtro muda). Dependemos dos campos
  // primitivos (não do objeto `filters`), senão o effect rodaria a cada render
  // — um objeto novo é criado pelo componente toda vez.
  useEffect(() => {
    let active = true;
    setIsLoading(true);
    getAuditLogs({
      limit: PAGE_SIZE,
      offset: 0,
      action: filters.action,
      resource_type: filters.resource_type,
    })
      .then((data) => {
        if (active) {
          setLogs(data);
          setOffset(0);
          setHasMore(data.length === PAGE_SIZE);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Falha ao carregar auditoria");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters.action, filters.resource_type]);

  const loadMore = useCallback(async () => {
    const nextOffset = offset + PAGE_SIZE;
    try {
      const data = await getAuditLogs({
        limit: PAGE_SIZE,
        offset: nextOffset,
        action: filters.action,
        resource_type: filters.resource_type,
      });
      // Concatena a nova página ao que já está na tela.
      setLogs((prev) => [...prev, ...data]);
      setOffset(nextOffset);
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar mais");
    }
  }, [offset, filters.action, filters.resource_type]);

  return { logs, isLoading, error, hasMore, loadMore };
}
