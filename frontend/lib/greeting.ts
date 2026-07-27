// Time of day for the Dashboard's greeting. Returns only the KEY — the full
// sentence lives in the messages (Dashboard.greeting, via {period, select, ...}).
// This function used to return "Bom dia" and the call site applied .toLowerCase():
// a Portuguese capitalization rule baked into the JSX, which would produce
// "good afternoon" in English.
//
// `hour` is a required parameter on purpose: reading it from the clock here would make
// the server (a different timezone) and the client disagree at hydration. The caller
// resolves the time after mounting.
export type Period = "morning" | "afternoon" | "evening";

export function periodForHour(hour: number): Period {
  return hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
}
