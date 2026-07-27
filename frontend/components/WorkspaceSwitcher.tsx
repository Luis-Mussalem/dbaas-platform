"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, Check } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { listCompanies } from "@/lib/api";
import type { Company } from "@/lib/types";

// Key that remembers which company the superuser left active. api.ts sends this id
// in the X-Company-Id header and the backend filters the data by it (Stage B). Absent
// (key removed) = "All companies" → the superuser sees everything.
const ACTIVE_KEY = "active_company_id";

// The Workspace changes according to the user's ROLE (mirrors the backend's
// get_current_superuser, which is what unlocks the company list):
//   • superuser  → switcher: dropdown with all companies, switches the active one.
//   • regular    → fixed label with their own company (user.company), no switching.
export function WorkspaceSwitcher() {
  const { user } = useAuth();
  const t = useTranslations("WorkspaceSwitcher");

  if (!user) return null;

  return user.is_superuser ? (
    <SuperuserSwitcher />
  ) : (
    <FixedWorkspace name={user.company?.name ?? t("noCompany")} />
  );
}

// ── Regular user: just shows their own company, no interaction ──
function FixedWorkspace({ name }: { name: string }) {
  const t = useTranslations("WorkspaceSwitcher");
  return (
    <div className="mb-4 flex items-center gap-2.5 rounded-md border border-border bg-surface px-3 py-2.5 text-left">
      <div className="h-6.5 w-6.5 shrink-0 rounded-md bg-linear-to-br from-primary to-info" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-medium">{name}</div>
        <div className="text-[12.5px] text-fg-3">{t("companyLabel")}</div>
      </div>
    </div>
  );
}

// ── Superuser: company-switching dropdown ──
function SuperuserSwitcher() {
  const t = useTranslations("WorkspaceSwitcher");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  // Fetches the companies (a route restricted to superuser). Same pattern as the other hooks:
  // an inline fetch in the effect, with an `active` guard to discard if unmounted.
  useEffect(() => {
    let active = true;
    listCompanies()
      .then((data) => {
        if (!active) return;
        setCompanies(data);
        // Restores the saved selection; if invalid/absent, default = "All" (null).
        const saved = localStorage.getItem(ACTIVE_KEY);
        const valid = data.find((c) => c.id === saved);
        setActiveId(valid?.id ?? null);
      })
      .catch(() => {
        if (active) setCompanies([]);
      });
    return () => {
      active = false;
    };
  }, []);

  function select(id: string | null) {
    // null = "All companies" → removes the key (no header → the backend shows everything).
    if (id === null) localStorage.removeItem(ACTIVE_KEY);
    else localStorage.setItem(ACTIVE_KEY, id);
    setOpen(false);
    // Reloads so every screen/hook re-fetches with the new X-Company-Id.
    window.location.reload();
  }

  const activeName = activeId
    ? companies.find((c) => c.id === activeId)?.name ?? t("selectCompany")
    : t("allCompanies");

  return (
    <div className="relative mb-3.5">
      <button
        onClick={() => companies.length > 0 && setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 rounded-md border border-border bg-surface px-3 py-2.5 text-left transition-colors hover:bg-surface-2"
      >
        <div className="h-6.5 w-6.5 shrink-0 rounded-md bg-linear-to-br from-primary to-info" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-medium">{activeName}</div>
          <div className="text-[12.5px] text-fg-3">{t("adminSubtitle")}</div>
        </div>
        <ChevronDown size={17} className="shrink-0 text-fg-3" />
      </button>

      {open && (
        <>
          {/* Invisible layer: a click outside closes the dropdown. */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <ul className="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-auto rounded-md border border-border bg-surface py-1 shadow-lg">
            {/* Global view: no company filter (sees all). */}
            <li>
              <button
                onClick={() => select(null)}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[15px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
              >
                <span className="flex-1 truncate">{t("allCompanies")}</span>
                {activeId === null && <Check size={15} className="shrink-0 text-brand" />}
              </button>
            </li>
            {companies.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => select(c.id)}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[15px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
                >
                  <span className="flex-1 truncate">{c.name}</span>
                  {c.id === activeId && <Check size={15} className="shrink-0 text-brand" />}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
