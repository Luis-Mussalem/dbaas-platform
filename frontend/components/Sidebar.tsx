"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";
import { useInstances } from "@/hooks/use-instances";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";
import {
  ACCOUNT_NAV,
  ADMIN_NAV,
  WORKSPACE_NAV,
  isActive,
  type NavItem,
} from "@/lib/nav";

export function Sidebar() {
  const pathname = usePathname();
  const t = useTranslations("Nav");
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
    <aside className="flex min-w-0 flex-col overflow-hidden border-r border-border bg-sidebar px-4 py-4">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-1.5 pb-4 text-[18px] font-semibold">
        <div className="flex h-8 w-8 items-center justify-center rounded-[8px] bg-primary text-[16px] font-bold text-primary-foreground">
          D
        </div>
        <span>DBaaS</span>
        <span className="ml-auto rounded bg-bg-2 px-1.5 py-0.5 text-[11.5px] font-medium text-fg-3">
          v0.1
        </span>
      </div>

      {/* Workspace: empresa atual (switcher p/ superuser, rótulo fixo p/ comum) */}
      <WorkspaceSwitcher />

      {/* Navegação */}
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
        <NavSection label={t("group.workspace")} />
        {WORKSPACE_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            label={t(item.key)}
            active={isActive(pathname, item.href)}
            // Contagem real só no item de Instâncias; oculta quando 0.
            badge={
              item.href === "/instances" && instanceCount > 0
                ? String(instanceCount)
                : undefined
            }
          />
        ))}
        {(user?.is_superuser || user?.role === "admin") && (
          <>
            <NavSection label={t("group.admin")} />
            {ADMIN_NAV.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                label={t(item.key)}
                active={isActive(pathname, item.href)}
              />
            ))}
          </>
        )}
        <NavSection label={t("group.account")} />
        {ACCOUNT_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            label={t(item.key)}
            active={isActive(pathname, item.href)}
          />
        ))}
      </nav>

      {/* Rodapé: operador logado + logout */}
      <div className="mt-2 border-t border-border px-1 pt-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8.5 w-8.5 items-center justify-center rounded-md bg-primary text-[13px] font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14.5px] font-medium text-foreground">
              {user?.email ?? "—"}
            </div>
            <div className="text-[12.5px] text-fg-3">{t("onlineNow")}</div>
          </div>
          <button
            onClick={handleLogout}
            title={t("logout")}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}

function NavSection({ label }: { label: string }) {
  return (
    <div className="px-3 pb-2 pt-4 text-[12px] font-semibold uppercase tracking-wider text-fg-3">
      {label}
    </div>
  );
}

function NavLink({
  item,
  label,
  active,
  badge,
}: {
  item: NavItem;
  label: string;
  active: boolean;
  badge?: string;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-[15px] font-medium transition-colors",
        active
          ? "bg-brand-subtle text-brand"
          : "text-fg-2 hover:bg-surface-2 hover:text-foreground"
      )}
    >
      <Icon size={19} className="shrink-0" />
      <span>{label}</span>
      {badge && (
        <span className="ml-auto rounded-full bg-bg-2 px-2 text-[12.5px] text-fg-3">
          {badge}
        </span>
      )}
    </Link>
  );
}
