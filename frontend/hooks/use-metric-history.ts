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
  window: MetricWindow = "1h"
): number[] {
  const [values, setValues] = useState<number[]>([]);

  useEffect(() => {
    let active = true;
    getMetricHistory(instanceId, metric, window)
      .then((res) => {
        if (active) setValues(res.points.map((p) => p.value));
      })
      .catch(() => {
        if (active) setValues([]);
      });
    return () => {
      active = false;
    };
  }, [instanceId, metric, window]);

  return values;
}
