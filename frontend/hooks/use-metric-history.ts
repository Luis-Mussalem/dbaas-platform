import { useEffect, useState } from "react";
import { getMetricHistory } from "@/lib/api";
import type { MetricWindow } from "@/lib/types";

// Busca a série temporal de uma métrica e devolve só os valores (number[]),
// prontos para o <Sparkline>. Mesmo padrão das outras hooks: fetch no mount,
// guard `active` para descartar resposta se o componente desmontar.
//
// `pollMs` (DASHBOARD_POLL_MS nos chamadores) mantém a série fresca: sem ele, o
// gráfico ficava congelado na última busca até um F5.
export function useMetricHistory(
  instanceId: string,
  metric: string,
  window: MetricWindow = "1h",
  pollMs?: number,
  points?: number,
  // Ver useResource: força a releitura imediata após uma ação da simulação.
  version?: number
): number[] {
  const [values, setValues] = useState<number[]>([]);

  useEffect(() => {
    let active = true;

    function load() {
      getMetricHistory(instanceId, metric, window, points)
        .then((res) => {
          if (active) setValues(res.points.map((p) => p.value));
        })
        .catch(() => {
          if (active) setValues([]);
        });
    }

    load();
    // Durante a simulação a série cresce a cada poucos segundos; fora dela, a
    // cada minuto (cadência do poller). O intervalo só some se o chamador
    // deliberadamente não passar um.
    const intervalId = pollMs ? setInterval(load, pollMs) : undefined;

    return () => {
      active = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [instanceId, metric, window, pollMs, points, version]);

  return values;
}
