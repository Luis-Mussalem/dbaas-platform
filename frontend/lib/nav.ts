import {
  Database,
  FlaskConical,
  HelpCircle,
  LayoutDashboard,
  ScrollText,
  Settings,
  Terminal,
  Users,
  type LucideIcon,
} from "lucide-react";

// Fonte única da navegação: a Sidebar monta os links e o Topbar deriva o
// breadcrumb daqui. Antes cada um tinha seu próprio mapa de URL → rótulo.
// `key` indexa Nav.* nas mensagens; o texto não vive mais neste arquivo.
// A união literal (em vez de `string`) é o que permite ao tsc validar t(key).
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
  { href: "/demo", key: "demo", icon: FlaskConical },
  { href: "/settings", key: "settings", icon: Settings },
  { href: "/help", key: "help", icon: HelpCircle },
];

export const ALL_NAV: NavItem[] = [...WORKSPACE_NAV, ...ADMIN_NAV, ...ACCOUNT_NAV];

// "/" só casa na raiz exata; as demais casam também nas subrotas
// (ex.: /instances ativo em /instances/abc).
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

// Chave de mensagem da rota atual — usada pelo breadcrumb.
export function navKeyFor(pathname: string): NavKey | undefined {
  return ALL_NAV.find((item) => item.href === pathname)?.key;
}
