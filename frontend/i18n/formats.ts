import type { Formats } from "next-intl";
import { CURRENCY, type Locale } from "./config";

// Global formats consumed via useFormatter(): format.number(v, "cost").
// `formats.number.cost` is the ONLY place where the currency is decided.
export function formatsFor(locale: Locale) {
  return {
    number: {
      cost: {
        style: "currency",
        currency: CURRENCY[locale],
        maximumFractionDigits: 0,
      },
      integer: { maximumFractionDigits: 0 },
      ratio1: { maximumFractionDigits: 1 },
      ratio2: { maximumFractionDigits: 2 },
    },
    dateTime: {
      date: { day: "2-digit", month: "2-digit", year: "numeric" },
      full: { dateStyle: "short", timeStyle: "medium" },
      clock: { hour: "2-digit", minute: "2-digit" },
    },
  } as const satisfies Formats;
}

export type AppFormats = ReturnType<typeof formatsFor>;
