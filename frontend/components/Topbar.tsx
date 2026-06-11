"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Plus, Sun, Moon } from "lucide-react";
import { useTheme } from "@/context/ThemeProvider";
import { Segmented } from "@/components/Segmented";

// Mapa de URL → título exibido no breadcrumb.
const TITLES: Record<string, string> = {
  "/": "Painel",
  "/instances": "Instâncias",
  "/sql": "Console SQL",
  "/audit": "Logs & Auditoria",
  "/settings": "Configurações",
  "/help": "Ajuda",
};

// Deriva o breadcrumb da URL (no protótipo isso vinha do estado `route`).
function useCrumbs(pathname: string): string[] {
  if (pathname.startsWith("/instances/")) return ["Instâncias", "Detalhe"];
  return [TITLES[pathname] ?? "Painel"];
}

export function Topbar() {
  const pathname = usePathname();
  const crumbs = useCrumbs(pathname);
  const { theme, toggleTheme } = useTheme();

  // Controles cosméticos por enquanto (i18n real entra na Fase D do redesign).
  // Mantidos para espelhar o layout do design; o estado é só visual.
  const [lang, setLang] = useState<"pt" | "en">("pt");

  return (
    <header className="flex h-13 shrink-0 items-center gap-3 border-b border-border bg-background px-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-[13px] text-fg-3">
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-fg-faint">/</span>}
            <span className={i === crumbs.length - 1 ? "font-medium text-foreground" : ""}>
              {c}
            </span>
          </span>
        ))}
      </div>

      <div className="flex-1" />

      {/* Idioma (cosmético até a Fase D de i18n) */}
      <div className="hidden sm:block">
        <Segmented
          size="sm"
          value={lang}
          onChange={setLang}
          options={[
            { value: "pt", label: "PT" },
            { value: "en", label: "EN" },
          ]}
        />
      </div>

      {/* Toggle de tema (sol/lua) — usa o ThemeProvider da Etapa 1 */}
      <button
        onClick={toggleTheme}
        title="Alternar tema"
        className="flex h-7.5 w-7.5 items-center justify-center rounded-md border border-border bg-surface text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
      </button>

      {/* Nova instância → abre o wizard de criação */}
      <Link
        href="/instances/new"
        className="flex h-7.5 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition hover:brightness-110"
      >
        <Plus size={14} />
        Nova instância
      </Link>
    </header>
  );
}
