import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

// Hook genérico de dados: colapsa o boilerplate idêntico dos hooks de fetch
// (busca inicial + guarda `active` + { data, isLoading, error, refresh }).
// Cada hook específico continua dono da sua API pública — este é só o motor.
//
// O `fetcher` DEVE ser estável entre renders (useCallback nos chamadores),
// senão o effect re-dispara a cada render.
interface UseResourceResult<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  // Exposto para hooks que mutam a lista localmente após create/delete
  // (ex.: use-instances), sem re-buscar tudo do backend.
  setData: Dispatch<SetStateAction<T | null>>;
}

export function useResource<T>(
  fetcher: () => Promise<T>,
  errorMessage: string,
  pollMs?: number
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

  // Busca inicial inline (setState dentro do .then/.catch, após o await) — evita
  // o aviso de "setState síncrono no effect". `active` descarta a resposta se o
  // componente desmontar antes dela chegar.
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
  }, [fetcher, errorMessage, pollMs]);

  return { data, isLoading, error, refresh, setData };
}
