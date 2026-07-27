import { cookies } from "next/headers";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALES } from "./config";
import { formatsFor } from "./formats";

// Per-request i18n config. Reading the cookie here makes every route dynamic — that's
// expected: there's no middleware, auth is already client-side, and all data comes from
// useEffect, so no page had static content to lose.
export default getRequestConfig(async () => {
  const store = await cookies();
  const cookieLocale = store.get(LOCALE_COOKIE)?.value;
  // Missing cookie (first visit) or tampered → English.
  const locale = hasLocale(LOCALES, cookieLocale) ? cookieLocale : DEFAULT_LOCALE;

  return {
    locale,
    // The template literal makes the bundler inline both JSONs into the
    // server bundle. Don't swap for fs.readFile: it would break the Docker
    // standalone build at runtime (ENOENT), and only show up in production.
    messages: (await import(`../messages/${locale}.json`)).default,
    formats: formatsFor(locale),
    // `now` pinned on the server and inherited by useNow(): without it, relativeTime
    // would diverge between server and client during hydration.
    now: new Date(),
    // timeZone deliberately left undefined: no date is rendered on the
    // server (they all come from useEffect). Careful: omitting it does NOT mean "use the
    // user's timezone" — next-intl falls back to the server runtime's timezone (UTC in the
    // container). What injects the browser's timezone is hooks/use-formatters.ts,
    // which every displayed date goes through.
  };
});
