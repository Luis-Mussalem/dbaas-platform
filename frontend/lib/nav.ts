import {
  Database,
  HelpCircle,
  Info,
  LayoutDashboard,
  ScrollText,
  Settings,
  Terminal,
  Users,
  type LucideIcon,
} from "lucide-react";

// Single source of navigation: the Sidebar builds the links and the Topbar derives the
// breadcrumb from here. Each one used to have its own URL → label map.
// `key` indexes Nav.* in the messages; the text no longer lives in this file.
// The literal union (instead of `string`) is what lets tsc validate t(key).
export type NavKey =
  | "dashboard"
  | "instances"
  | "sql"
  | "employees"
  | "audit"
  | "settings"
  | "help"
  | "demo";

export type NavItem = { href: string; key: NavKey; icon: LucideIcon };

export const WORKSPACE_NAV: NavItem[] = [
  { href: "/", key: "dashboard", icon: LayoutDashboard },
  { href: "/instances", key: "instances", icon: Database },
  { href: "/sql", key: "sql", icon: Terminal },
];

export const ADMIN_NAV: NavItem[] = [
  { href: "/admin/users", key: "employees", icon: Users },
  { href: "/audit", key: "audit", icon: ScrollText },
];

export const ACCOUNT_NAV: NavItem[] = [
  { href: "/demo", key: "demo", icon: Info },
  { href: "/settings", key: "settings", icon: Settings },
  { href: "/help", key: "help", icon: HelpCircle },
];

export const ALL_NAV: NavItem[] = [...WORKSPACE_NAV, ...ADMIN_NAV, ...ACCOUNT_NAV];

// "/" only matches the exact root; the others also match subroutes
// (e.g.: /instances active on /instances/abc).
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

// Message key for the current route — used by the breadcrumb.
export function navKeyFor(pathname: string): NavKey | undefined {
  return ALL_NAV.find((item) => item.href === pathname)?.key;
}
