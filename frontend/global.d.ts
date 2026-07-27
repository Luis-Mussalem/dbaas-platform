import type { Locale } from "@/i18n/config";
import type { AppFormats } from "@/i18n/formats";
import type messages from "./messages/en.json";

// en.json is the source of the types: a missing key in t() becomes a tsc error,
// and pt.json is checked against this same type in i18n/messages.check.ts.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof messages;
    Formats: AppFormats;
  }
}
