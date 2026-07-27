import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

// Generic data hook: collapses the identical boilerplate of the fetch hooks
// (initial fetch + `active` guard + { data, isLoading, error, refresh }).
// Each specific hook still owns its public API — this is just the engine.
//
// `fetcher` MUST be stable across renders (useCallback in the callers),
// otherwise the effect re-triggers on every render.
interface UseResourceResult<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  // Exposed for hooks that mutate the list locally after create/delete
  // (e.g.: use-instances), without re-fetching everything from the backend.
  setData: Dispatch<SetStateAction<T | null>>;
}

export function useResource<T>(
  fetcher: () => Promise<T>,
  errorMessage: string,
  pollMs?: number,
  // Changes when something external already knows the data changed (a
  // simulation action, for example). Only participates in the effect's dependencies: a
  // change redoes the fetch right away, instead of waiting for the next `pollMs`.
  version?: number
): UseResourceResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [fetcher, errorMessage]);

  // Inline initial fetch (setState inside .then/.catch, after the await) — avoids
  // the "synchronous setState in effect" warning. `active` discards the response if the
  // component unmounts before it arrives.
  useEffect(() => {
    let active = true;

    function load() {
      fetcher()
        .then((result) => {
          if (active) {
            setData(result);
            setError(null);
          }
        })
        .catch((err) => {
          if (active) {
            setError(err instanceof Error ? err.message : errorMessage);
          }
        })
        .finally(() => {
          if (active) setIsLoading(false);
        });
    }

    load();
    const intervalId = pollMs ? setInterval(load, pollMs) : undefined;

    return () => {
      active = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [fetcher, errorMessage, pollMs, version]);

  return { data, isLoading, error, refresh, setData };
}
