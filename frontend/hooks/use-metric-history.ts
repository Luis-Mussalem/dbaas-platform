import { useEffect, useState } from "react";
import { getMetricHistory } from "@/lib/api";
import type { MetricWindow } from "@/lib/types";

// Busca a série temporal de uma métrica e devolve só os valores (number[]),
// prontos para o <Sparkline>. Mesmo padrão das outras hooks: fetch no mount,
// guard `active` para descartar resposta se o componente desmontar. Sem polling
// (a série histórica muda devagar; o número "ao vivo" continua vindo de useMetrics).
export function useMetricHistory(
  instanceId: string,
  metric: string,
  window: MetricWindow = "1h",
  pollMs?: number,
  points?: number
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
    // Durante a simulação de uso a série cresce a cada poucos segundos; fora
    // dela não há o que repetir e o intervalo fica ausente.
    const intervalId = pollMs ? setInterval(load, pollMs) : undefined;

    return () => {
      active = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [instanceId, metric, window, pollMs, points]);

  return values;
}
