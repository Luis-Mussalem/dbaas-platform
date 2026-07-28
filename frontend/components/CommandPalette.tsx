"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  CornerDownLeft,
  Database,
  LogOut,
  Moon,
  Plus,
  Search,
  Sun,
  Languages,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeProvider";
import { useInstances } from "@/hooks/use-instances";
import { useCanManage } from "@/hooks/use-permissions";
import { setLocale } from "@/i18n/locale-action";
import {
  ACCOUNT_NAV,
  ADMIN_NAV,
  WORKSPACE_NAV,
  type NavItem,
} from "@/lib/nav";

// Event the Topbar button fires to open the palette without a dedicated
// provider — the global listener (Ctrl+K) and the button converge on the same toggle.
export const OPEN_EVENT = "command-palette:open";

const DOT: Record<string, string> = {
  running: "bg-ok",
  stopped: "bg-fg-3",
  failed: "bg-danger",
};

type Command = {
  id: string;
  label: string;
  group: string;
  icon: LucideIcon;
  keywords: string;
  hint?: string;
  dot?: string;
  run: () => void;
};

// Global command palette (Ctrl+K / ⌘K on Mac): navigation, jumping to instances, and quick
// actions in one place. Complements the Topbar's "/" search (instances only).
export function CommandPalette() {
  const t = useTranslations("CommandPalette");
  const tNav = useTranslations("Nav");
  const router = useRouter();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const canManage = useCanManage();
  const { instances } = useInstances();
  const locale = useLocale();
  const [, startTransition] = useTransition();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  function close() {
    setOpen(false);
    setQuery("");
    setActive(0);
  }

  // Closes and then runs — the navigation/action happens with the overlay already gone.
  function runAndClose(fn: () => void) {
    close();
    fn();
  }

  const isAdmin = Boolean(user?.is_superuser || user?.role === "admin");

  // ── Commands ────────────────────────────────────────────────────────────────
  const commands = useMemo<Command[]>(() => {
    const navItems: NavItem[] = [
      ...WORKSPACE_NAV,
      ...(isAdmin ? ADMIN_NAV : []),
      ...ACCOUNT_NAV,
    ];
    const nav: Command[] = navItems.map((item) => ({
      id: `nav:${item.href}`,
      label: tNav(item.key),
      group: t("group.navigation"),
      icon: item.icon,
      keywords: `${tNav(item.key)} ${item.href}`,
      run: () => router.push(item.href),
    }));

    const instanceCmds: Command[] = instances.map((inst) => ({
      id: `inst:${inst.id}`,
      label: inst.name,
      group: t("group.instances"),
      icon: Database,
      keywords: `${inst.name} ${inst.region ?? ""}`,
      dot: DOT[inst.status] ?? "bg-warn",
      run: () => router.push(`/instances/${inst.id}`),
    }));

    const actions: Command[] = [
      // "New instance" is only offered to who can actually provision one —
      // members observe, admins operate (hooks/use-permissions).
      ...(canManage
        ? [
            {
              id: "act:new",
              label: t("action.newInstance"),
              group: t("group.actions"),
              icon: Plus,
              keywords: `${t("action.newInstance")} create new`,
              run: () => router.push("/instances/new"),
            } satisfies Command,
          ]
        : []),
      {
        id: "act:theme",
        label: t("action.toggleTheme"),
        group: t("group.actions"),
        icon: theme === "dark" ? Sun : Moon,
        keywords: `${t("action.toggleTheme")} dark light`,
        run: toggleTheme,
      },
      {
        id: "act:lang",
        label: t("action.switchLanguage"),
        group: t("group.actions"),
        icon: Languages,
        keywords: `${t("action.switchLanguage")} idioma language en pt`,
        hint: locale === "en" ? "PT" : "EN",
        run: () =>
          startTransition(() => void setLocale(locale === "en" ? "pt" : "en")),
      },
      {
        id: "act:logout",
        label: t("action.signOut"),
        group: t("group.actions"),
        icon: LogOut,
        keywords: `${t("action.signOut")} logout sair`,
        run: () => {
          logout();
          router.push("/login");
        },
      },
    ];

    return [...nav, ...instanceCmds, ...actions];
  }, [
    canManage,
    instances,
    isAdmin,
    locale,
    theme,
    toggleTheme,
    logout,
    router,
    startTransition,
    t,
    tNav,
  ]);

  // ── Filter ───────────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.keywords.toLowerCase().includes(q));
  }, [commands, query]);

  // Groups while preserving the groups' insertion order.
  const groups = useMemo(() => {
    const map = new Map<string, Command[]>();
    for (const cmd of filtered) {
      const arr = map.get(cmd.group);
      if (arr) arr.push(cmd);
      else map.set(cmd.group, [cmd]);
    }
    return Array.from(map.entries());
  }, [filtered]);

  // ── Global open shortcut (Ctrl+K / ⌘K on Mac) + button event ────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    function onOpen() {
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  // Focuses the input on open (the active index is reset in the input's onChange).
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Keeps the active item visible during keyboard navigation.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (filtered.length ? (a + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) =>
        filtered.length ? (a - 1 + filtered.length) % filtered.length : 0,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[active];
      if (cmd) runAndClose(cmd.run);
    }
  }

  return (
    <div
      className="fixed inset-0 z-120 flex items-start justify-center bg-black/40 p-4 pt-[12vh] animate-in fade-in"
      onMouseDown={close}
      role="dialog"
      aria-modal="true"
      aria-label={t("openLabel")}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-surface shadow-2xl animate-in slide-in-from-top-2"
      >
        {/* Campo de busca */}
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search size={16} className="shrink-0 text-fg-3" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            placeholder={t("placeholder")}
            className="h-12 flex-1 bg-transparent text-[14px] text-foreground placeholder:text-fg-faint focus:outline-none"
          />
          <kbd className="hidden shrink-0 rounded border border-border bg-bg-2 px-1.5 py-0.5 text-[10px] text-fg-3 sm:block">
            esc
          </kbd>
        </div>

        {/* Resultados */}
        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <p className="px-4 py-8 text-center text-[13px] text-fg-3">
              {t("empty")}
            </p>
          ) : (
            groups.map(([group, items]) => (
              <div key={group} className="mb-1 last:mb-0">
                <div className="px-4 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-wider text-fg-3">
                  {group}
                </div>
                {items.map((cmd) => {
                  const idx = filtered.indexOf(cmd);
                  const isActive = idx === active;
                  const Icon = cmd.icon;
                  return (
                    <button
                      key={cmd.id}
                      data-active={isActive}
                      onMouseMove={() => setActive(idx)}
                      onClick={() => runAndClose(cmd.run)}
                      className={`flex w-full items-center gap-3 px-4 py-2 text-left text-[13px] transition-colors ${
                        isActive ? "bg-brand-subtle text-brand" : "text-fg-2"
                      }`}
                    >
                      {cmd.dot ? (
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${cmd.dot}`} />
                      ) : (
                        <Icon size={15} className="shrink-0 text-fg-3" />
                      )}
                      <span
                        className={`flex-1 truncate ${cmd.dot ? "font-mono" : ""}`}
                      >
                        {cmd.label}
                      </span>
                      {cmd.hint && (
                        <span className="shrink-0 rounded border border-border bg-bg-2 px-1.5 text-[10.5px] text-fg-3">
                          {cmd.hint}
                        </span>
                      )}
                      {isActive && (
                        <CornerDownLeft size={13} className="shrink-0 text-fg-3" />
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer with keyboard hints */}
        <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-[11px] text-fg-3">
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-border bg-bg-2 px-1">↑</kbd>
            <kbd className="rounded border border-border bg-bg-2 px-1">↓</kbd>
            {t("hint.navigate")}
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border border-border bg-bg-2 px-1">↵</kbd>
            {t("hint.select")}
          </span>
          <span className="ml-auto flex items-center gap-1">
            <kbd className="rounded border border-border bg-bg-2 px-1">esc</kbd>
            {t("hint.close")}
          </span>
        </div>
      </div>
    </div>
  );
}
