import { cookies } from "next/headers";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALES } from "./config";
import { formatsFor } from "./formats";

// Config de i18n por request. Ler o cookie aqui torna toda rota dinâmica — é
// esperado: não há middleware, a auth já é client-side e todos os dados vêm de
// useEffect, então nenhuma página tinha conteúdo estático a perder.
export default getRequestConfig(async () => {
  const store = await cookies();
  const cookieLocale = store.get(LOCALE_COOKIE)?.value;
  // Cookie ausente (primeira visita) ou adulterado → inglês.
  const locale = hasLocale(LOCALES, cookieLocale) ? cookieLocale : DEFAULT_LOCALE;

  return {
    locale,
    // O template literal faz o bundler embutir os dois JSONs no bundle do
    // servidor. Não trocar por fs.readFile: quebraria o build standalone do
    // Docker em runtime (ENOENT), e só apareceria em produção.
    messages: (await import(`../messages/${locale}.json`)).default,
    formats: formatsFor(locale),
    // `now` fixado no servidor e herdado por useNow(): sem ele, relativeTime
    // diverge entre servidor e cliente na hidratação.
    now: new Date(),
    // timeZone deliberadamente indefinido: nenhuma data é renderizada no
    // servidor (todas vêm de useEffect), então o fuso local do usuário é o certo.
  };
});
