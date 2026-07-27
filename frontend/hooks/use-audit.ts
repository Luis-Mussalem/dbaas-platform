import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getAuditLogs } from "@/lib/api";
import type { AuditLog } from "@/lib/types";

// How many records to fetch per page. If the response comes back with exactly this
// size, we assume there COULD be more (enables "Load more").
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

// Offset/limit pagination that ACCUMULATES: unlike the other hooks (which
// replace the list on every fetch), here the first page replaces and the
// following ones are APPENDED at the end (setLogs(prev => [...prev, ...data])).
// Changing any filter resets everything to page 0.
export function useAudit(filters: AuditFilters): UseAuditResult {
  const t = useTranslations("Audit");
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  // First page (and reset when a filter changes). We depend on the
  // primitive fields (not the `filters` object), otherwise the effect would run on every render
  // — a new object is created by the component every time.
  useEffect(() => {
    let active = true;
    // Synchronous reset to "loading" before the refetch (filter change).
    // Intentional and abort-guarded; set-state-in-effect is too conservative here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
        if (active) setError(err instanceof Error ? err.message : t("loadFailed"));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters.action, filters.resource_type, t]);

  const loadMore = useCallback(async () => {
    const nextOffset = offset + PAGE_SIZE;
    try {
      const data = await getAuditLogs({
        limit: PAGE_SIZE,
        offset: nextOffset,
        action: filters.action,
        resource_type: filters.resource_type,
      });
      // Appends the new page to what's already on screen.
      setLogs((prev) => [...prev, ...data]);
      setOffset(nextOffset);
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("loadMoreFailed"));
    }
  }, [offset, filters.action, filters.resource_type, t]);

  return { logs, isLoading, error, hasMore, loadMore };
}
