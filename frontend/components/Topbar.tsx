"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Plus, Sun, Moon, Files } from "lucide-react";
import { useTheme } from "@/context/ThemeProvider";
import { Segmented } from "@/components/Segmented";
import { InstanceSearch } from "@/components/InstanceSearch";
import { SimulationButton } from "@/components/SimulationButton";
import { OPEN_EVENT } from "@/components/CommandPalette";
import { navKeyFor } from "@/lib/nav";
import { setLocale } from "@/i18n/locale-action";
import type { Locale } from "@/i18n/config";

// Breadcrumb derivado da URL. Os rótulos vêm de lib/nav.ts + mensagens Nav.*,
// a mesma fonte que a Sidebar usa — antes havia um mapa próprio aqui.
function useCrumbs(pathname: string): string[] {
  const t = useTranslations("Nav");
  const tTop = useTranslations("Topbar");

  if (pathname.startsWith("/instances/")) return [t("instances"), tTop("crumb.detail")];

  const key = navKeyFor(pathname);
  if (pathname.startsWith("/admin/")) {
    return [tTop("crumb.admin"), key ? t(key) : pathname];
  }
  return [key ? t(key) : t("dashboard")];
}

export function Topbar() {
  const pathname = usePathname();
  const crumbs = useCrumbs(pathname);
  const t = useTranslations("Topbar");
  const tCmd = useTranslations("CommandPalette");
  const { theme, toggleTheme } = useTheme();

  // O locale é a verdade do cookie, servida pelo provider — sem estado local
  // duplicado. A Server Action grava o cookie e revalida o layout.
  const locale = useLocale();
  const [isPending, startTransition] = useTransition();

  return (
    <header className="flex h-16 shrink-0 items-center gap-3.5 border-b border-border bg-background px-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-[15px] text-fg-3">
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

      {/* Busca rápida de instâncias (atalho "/") */}
      <InstanceSearch />

      {/* Abre o command palette (Ctrl+K) — mesmo evento do atalho global */}
      <button
        onClick={() => window.dispatchEvent(new CustomEvent(OPEN_EVENT))}
        title={tCmd("openLabel")}
        aria-label={tCmd("openLabel")}
        className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface pl-2.5 pr-3 text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        <Files size={17} className="shrink-0" />
        <kbd className="hidden text-[13px] font-medium tracking-wide text-fg-3 sm:block">
          Ctrl&nbsp;K
        </kbd>
      </button>

      {/* Idioma — grava o cookie via Server Action e revalida o layout */}
      <div className={`hidden sm:block ${isPending ? "pointer-events-none opacity-60" : ""}`}>
        <Segmented<Locale>
          size="lg"
          value={locale}
          onChange={(next) => startTransition(() => void setLocale(next))}
          options={[
            { value: "en", label: "EN" },
            { value: "pt", label: "PT" },
          ]}
        />
      </div>

      {/* Toggle de tema (sol/lua) — usa o ThemeProvider da Etapa 1 */}
      <button
        onClick={toggleTheme}
        title={t("toggleTheme")}
        className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      {/* Simular uso ↔ Parar — só aparece em modo demo */}
      <SimulationButton />

      {/* Nova instância → abre o wizard de criação */}
      <Link
        href="/instances/new"
        className="flex h-9 items-center gap-2 rounded-md bg-primary px-3.5 text-[15px] font-medium text-primary-foreground transition hover:brightness-110"
      >
        <Plus size={17} />
        {t("newInstance")}
      </Link>
    </header>
  );
}
