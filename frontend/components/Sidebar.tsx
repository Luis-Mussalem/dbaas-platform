"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Database,
  Terminal,
  ScrollText,
  Settings,
  HelpCircle,
  LogOut,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";
import { useInstances } from "@/hooks/use-instances";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";

// Itens de navegação — `href` é a URL real (a fonte da verdade do "ativo").
type NavItem = { href: string; label: string; icon: LucideIcon; badge?: string };

const WORKSPACE_NAV: NavItem[] = [
  { href: "/", label: "Painel", icon: LayoutDashboard },
  { href: "/instances", label: "Instâncias", icon: Database },
  { href: "/sql", label: "Console SQL", icon: Terminal, badge: "Em breve" },
];

const ACCOUNT_NAV: NavItem[] = [
  { href: "/audit", label: "Logs & Auditoria", icon: ScrollText },
  { href: "/settings", label: "Configurações", icon: Settings },
  { href: "/help", label: "Ajuda", icon: HelpCircle },
];

// "/" só fica ativo na raiz exata; as demais ficam ativas também nas subrotas
// (ex.: /instances ativo em /instances/abc).
function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { instances } = useInstances();
  const router = useRouter();

  // Badge de "Instâncias" = contagem real (oculta quando 0), em vez de um número fixo.
  const instanceCount = instances.length;

  function handleLogout() {
    logout();
    router.push("/login");
  }

  // Iniciais do operador a partir do email (não temos "nome" no backend).
  const initials = (user?.email ?? "?").slice(0, 2).toUpperCase();

  return (
    <aside className="flex min-w-0 flex-col overflow-hidden border-r border-border bg-sidebar px-3 py-3.5">
      {/* Brand */}
      <div className="flex items-center gap-2 px-1.5 pb-3.5 text-[15px] font-semibold">
        <div className="flex h-6.5 w-6.5 items-center justify-center rounded-[7px] bg-primary text-[14px] font-bold text-primary-foreground">
          D
        </div>
        <span>DBaaS</span>
        <span className="ml-auto rounded bg-bg-2 px-1.5 py-0.5 text-[10px] font-medium text-fg-3">
          v0.1
        </span>
      </div>

      {/* Workspace: empresa atual (switcher p/ superuser, rótulo fixo p/ comum) */}
      <WorkspaceSwitcher />

      {/* Navegação */}
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
        <NavSection label="Workspace" />
        {WORKSPACE_NAV.map((item) => {
          // Injeta a contagem real no item de Instâncias; os demais ficam como definidos.
          const withBadge =
            item.href === "/instances" && instanceCount > 0
              ? { ...item, badge: String(instanceCount) }
              : item;
          return (
            <NavLink key={item.href} item={withBadge} active={isActive(pathname, item.href)} />
          );
        })}
        <NavSection label="Conta" />
        {ACCOUNT_NAV.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(pathname, item.href)} />
        ))}
      </nav>

      {/* Rodapé: operador logado + logout */}
      <div className="mt-2 border-t border-border px-1 pt-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-[11px] font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-medium text-foreground">
              {user?.email ?? "—"}
            </div>
            <div className="text-[11px] text-fg-3">Online agora</div>
          </div>
          <button
            onClick={handleLogout}
            title="Sair"
            className="flex h-6.5 w-6.5 items-center justify-center rounded-md border border-border bg-surface text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavSection({ label }: { label: string }) {
  return (
    <div className="px-2.5 pb-1.5 pt-3.5 text-[10.5px] font-semibold uppercase tracking-wider text-fg-3">
      {label}
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors",
        active
          ? "bg-brand-subtle text-brand"
          : "text-fg-2 hover:bg-surface-2 hover:text-foreground"
      )}
    >
      <Icon size={16} className="shrink-0" />
      <span>{item.label}</span>
      {item.badge && (
        <span className="ml-auto rounded-full bg-bg-2 px-1.5 text-[11px] text-fg-3">
          {item.badge}
        </span>
      )}
    </Link>
  );
}
