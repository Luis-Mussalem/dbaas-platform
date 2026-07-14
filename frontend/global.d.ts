import type { Locale } from "@/i18n/config";
import type { AppFormats } from "@/i18n/formats";
import type messages from "./messages/en.json";

// en.json é a fonte dos tipos: uma chave inexistente em t() vira erro de tsc,
// e pt.json é checado contra este mesmo tipo em i18n/messages.check.ts.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof messages;
    Formats: AppFormats;
  }
}
