"use client";

import { useCallback, useMemo } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";

// Formatação sensível a locale. Substitui lib/format.ts, cujas funções eram
// puras e por isso não tinham como conhecer o idioma (viviam com "pt-BR" cravado).
// Como hook, cada chamada usa os formatos de i18n/formats.ts do locale ativo.

// Fuso do navegador, resolvido uma vez. Sem isto, o next-intl herda o timeZone
// do runtime do SERVIDOR — que no container é UTC — e todo horário aparecia
// adiantado (3h no Brasil). Como nenhuma data é renderizada no servidor (todas
// vêm de fetch em efeito), passar o fuso do cliente é o certo e não gera
// divergência de hidratação: no servidor fica undefined, como antes.
const BROWSER_TIME_ZONE =
  typeof window === "undefined"
    ? undefined
    : Intl.DateTimeFormat().resolvedOptions().timeZone;

export function useFormatters() {
  const format = useFormatter();
  const t = useTranslations("Common");
  // Um relógio só para toda a árvore; `now` inicial vem do servidor (request.ts),
  // o que evita divergência de hidratação no tempo relativo.
  const now = useNow({ updateInterval: 60_000 });

  // Bytes → "1,5 GB" (pt) / "1.5 GB" (en). O loop de 1024 é lógica, não
  // formatação — só o número passa pelo Intl. A unidade (B/KB/MB) é neutra.
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
      // 1 casa decimal só quando o número é pequeno (ex.: 1.5 GB), senão inteiro.
      const style = n < 10 && i > 0 ? "ratio1" : "integer";
      return `${format.number(n, style)} ${units[i]}`;
    },
    [format, t]
  );

  return useMemo(
    () => ({
      bytes,
      // 1046 → "1.046" (pt) / "1,046" (en)
      number: (value: number | null | undefined) =>
        value == null ? t("none") : format.number(value, "integer"),
      // Moeda decidida em i18n/formats.ts: R$ em pt, US$ em en.
      cost: (value: number | null | undefined) =>
        value == null ? t("none") : format.number(value, "cost"),
      // Casas decimais fixas para métricas (ex.: 98.8% de cache hit).
      ratio: (value: number | null | undefined, digits: 1 | 2 = 1) =>
        value == null ? t("none") : format.number(value, digits === 1 ? "ratio1" : "ratio2"),
      // "há 5 min" / "5 minutes ago" — e, ao contrário do timeAgo antigo,
      // não satura em dias ("2 months ago").
      ago: (iso: string) => format.relativeTime(new Date(iso), now),
      dateTime: (iso: string, style: "date" | "full" | "clock") =>
        format.dateTime(new Date(iso), style, { timeZone: BROWSER_TIME_ZONE }),
    }),
    [bytes, format, now, t]
  );
}
