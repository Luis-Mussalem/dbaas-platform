import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { ThemeProvider } from "@/context/ThemeProvider";
import { AuthProvider } from "@/context/AuthContext";
import { ToastProvider } from "@/context/ToastProvider";
import { ConfirmProvider } from "@/context/ConfirmProvider";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

// Dinâmico (não `const metadata`) para que o <title> siga o locale do cookie.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("title"), description: t("description") };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Locale do cookie (i18n/request.ts). Sem cookie → "en".
  const locale = await getLocale();

  return (
    <html
      lang={locale}
      // "dark" é o tema inicial renderizado no servidor; o ThemeProvider
      // reconcilia com o localStorage no cliente. suppressHydrationWarning
      // silencia o aviso do React quando essa classe difere entre os dois.
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {/* Mais externo: os demais providers têm texto próprio e precisam de
            useTranslations. Sem props — herda locale/messages/formats/now do
            getRequestConfig por ser renderizado de um Server Component. */}
        <NextIntlClientProvider>
          <ThemeProvider>
            <AuthProvider>
              <ToastProvider>
                <ConfirmProvider>{children}</ConfirmProvider>
              </ToastProvider>
            </AuthProvider>
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}