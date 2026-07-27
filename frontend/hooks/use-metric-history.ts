import { useEffect, useState } from "react";
import { getMetricHistory } from "@/lib/api";
import type { MetricWindow } from "@/lib/types";

// Fetches a metric's time series and returns only the values (number[]),
// ready for <Sparkline>. Same pattern as the other hooks: fetch on mount,
// `active` guard to discard the response if the component unmounts.
//
// `pollMs` (DASHBOARD_POLL_MS in the callers) keeps the series fresh: without it, the
// chart would stay frozen on the last fetch until an F5.
export function useMetricHistory(
  instanceId: string,
  metric: string,
  window: MetricWindow = "1h",
  pollMs?: number,
  points?: number,
  // See useResource: forces an immediate re-read after a simulation action.
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
    // During the simulation the series grows every few seconds; outside of it,
    // every minute (the poller's cadence). The interval only disappears if the caller
    // deliberately doesn't pass one.
    const intervalId = pollMs ? setInterval(load, pollMs) : undefined;

    return () => {
      active = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [instanceId, metric, window, pollMs, points, version]);

  return values;
}
