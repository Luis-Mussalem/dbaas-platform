"use client";

import { useCallback, useMemo } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";

// Locale-sensitive formatting. Replaces lib/format.ts, whose functions were
// pure and therefore had no way to know the language (they lived with "pt-BR" hardcoded).
// As a hook, every call uses the active locale's formats from i18n/formats.ts.

// Browser timezone, resolved once. Without this, next-intl inherits the
// SERVER runtime's timeZone — which in the container is UTC — and every time would show up
// ahead (3h in Brazil). Since no date is rendered on the server (they all
// come from a fetch in an effect), passing the client's timezone is correct and doesn't cause
// a hydration mismatch: on the server it stays undefined, as before.
const BROWSER_TIME_ZONE =
  typeof window === "undefined"
    ? undefined
    : Intl.DateTimeFormat().resolvedOptions().timeZone;

export function useFormatters() {
  const format = useFormatter();
  const t = useTranslations("Common");
  // A single clock for the whole tree; the initial `now` comes from the server (request.ts),
  // which avoids a hydration mismatch in relative time.
  const now = useNow({ updateInterval: 60_000 });

  // Bytes → "1.5 GB" (en) / "1,5 GB" (pt). The 1024 loop is logic, not
  // formatting — only the number goes through Intl. The unit (B/KB/MB) is neutral.
  const bytes = useCallback(
    (value: number | null | undefined): string => {
      if (value == null || value <= 0) return t("none");
      const units = ["B", "KB", "MB", "GB", "TB"];
      let n = value;
      let i = 0;
      while (n >= 1024 && i < units.length - 1) {
        n /= 1024;
        i++;
      }
      // 1 decimal place only when the number is small (e.g.: 1.5 GB), otherwise an integer.
      const style = n < 10 && i > 0 ? "ratio1" : "integer";
      return `${format.number(n, style)} ${units[i]}`;
    },
    [format, t]
  );

  return useMemo(
    () => ({
      bytes,
      // 1046 → "1,046" (en) / "1.046" (pt)
      number: (value: number | null | undefined) =>
        value == null ? t("none") : format.number(value, "integer"),
      // Currency decided in i18n/formats.ts: US$ in en, R$ in pt.
      cost: (value: number | null | undefined) =>
        value == null ? t("none") : format.number(value, "cost"),
      // Fixed decimal places for metrics (e.g.: 98.8% cache hit).
      ratio: (value: number | null | undefined, digits: 1 | 2 = 1) =>
        value == null ? t("none") : format.number(value, digits === 1 ? "ratio1" : "ratio2"),
      // "5 minutes ago" — and, unlike the old timeAgo, doesn't saturate
      // at days ("2 months ago").
      ago: (iso: string) => format.relativeTime(new Date(iso), now),
      dateTime: (iso: string, style: "date" | "full" | "clock") =>
        format.dateTime(new Date(iso), style, { timeZone: BROWSER_TIME_ZONE }),
    }),
    [bytes, format, now, t]
  );
}
