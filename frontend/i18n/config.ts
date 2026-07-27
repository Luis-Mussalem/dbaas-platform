// Single source of truth for i18n: supported locales, default, and currency per locale.
// No i18n routing — the locale doesn't appear in the URL; it lives in a cookie (see request.ts).

export const LOCALES = ["en", "pt"] as const;
export type Locale = (typeof LOCALES)[number];

// English is the default on first visit (repo/portfolio with an international audience).
export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_COOKIE = "NEXT_LOCALE";

export type Currency = "USD" | "BRL";

// "en"/"pt" without a region: the CLDR resolves pt → BR and en → US, preserving the
// current format (1,046 / R$ 1.046). If pt-PT is ever needed, change it here.
export const CURRENCY: Record<Locale, Currency> = {
  en: "USD",
  pt: "BRL",
};
