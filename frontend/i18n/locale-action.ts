"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { LOCALE_COOKIE, type Locale } from "./config";

// A Server Action instead of document.cookie + router.refresh(): the cookie is written
// BEFORE the RSC payload is recomputed (no race) and can be HttpOnly — the
// client never needs to read it, the locale arrives via useLocale().
export async function setLocale(locale: Locale) {
  (await cookies()).set(LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
    httpOnly: true,
  });
  // Required: the locale affects the root layout (<html lang> + messages), not just
  // the page. Without this, lang stays stale until a hard reload.
  revalidatePath("/", "layout");
}
