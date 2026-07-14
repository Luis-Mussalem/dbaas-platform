// Fonte única de verdade do i18n: locales suportados, padrão e moeda por locale.
// Sem i18n routing — o locale não aparece na URL; vive num cookie (ver request.ts).

export const LOCALES = ["en", "pt"] as const;
export type Locale = (typeof LOCALES)[number];

// Inglês é o padrão da primeira visita (repo/portfólio com público internacional).
export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_COOKIE = "NEXT_LOCALE";

export type Currency = "USD" | "BRL";

// "en"/"pt" sem região: o CLDR resolve pt → BR e en → US, preservando o
// formato atual (1.046 / R$ 1.046). Se um dia precisar de pt-PT, muda-se aqui.
export const CURRENCY: Record<Locale, Currency> = {
  en: "USD",
  pt: "BRL",
};
