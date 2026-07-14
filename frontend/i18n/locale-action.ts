"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { LOCALE_COOKIE, type Locale } from "./config";

// Server Action em vez de document.cookie + router.refresh(): o cookie é gravado
// ANTES de o RSC payload ser recalculado (sem corrida) e pode ser HttpOnly — o
// cliente nunca precisa lê-lo, o locale chega via useLocale().
export async function setLocale(locale: Locale) {
  (await cookies()).set(LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
    httpOnly: true,
  });
  // Obrigatório: o locale afeta o root layout (<html lang> + mensagens), não só
  // a página. Sem isso o lang fica defasado até um hard reload.
  revalidatePath("/", "layout");
}
