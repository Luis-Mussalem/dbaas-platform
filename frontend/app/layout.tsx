import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/context/ThemeProvider";
import { AuthProvider } from "@/context/AuthContext";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "DBaaS Platform",
  description: "Database-as-a-Service — manage PostgreSQL instances",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="pt-BR"
      // "dark" é o tema inicial renderizado no servidor; o ThemeProvider
      // reconcilia com o localStorage no cliente. suppressHydrationWarning
      // silencia o aviso do React quando essa classe difere entre os dois.
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} dark h-full antialiased`}
      data-dir="habitat"
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}