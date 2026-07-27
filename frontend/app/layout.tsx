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

// Dynamic (not `const metadata`) so the <title> follows the cookie's locale.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("title"), description: t("description") };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Locale from the cookie (i18n/request.ts). No cookie → "en".
  const locale = await getLocale();

  return (
    <html
      lang={locale}
      // "dark" is the initial theme rendered on the server; ThemeProvider
      // reconciles it with localStorage on the client. suppressHydrationWarning
      // silences React's warning when this class differs between the two.
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} dark h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {/* Outermost: the other providers have their own text and need
            useTranslations. No props — inherits locale/messages/formats/now from
            getRequestConfig since it's rendered from a Server Component. */}
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