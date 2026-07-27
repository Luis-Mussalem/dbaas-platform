// Refresh cadence for the dashboard's data screens. It used to come from
// SimulationProvider (5s while a reel was running, 30s at rest); with the reel
// removed, the fleet has a stable baseline of activity and a single interval is enough.
export const DASHBOARD_POLL_MS = 10_000;
