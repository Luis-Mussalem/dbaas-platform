"use client";

import { useTranslations } from "next-intl";
import { Check, Minus, ShieldCheck } from "lucide-react";

// Capability matrix by role — static, reflecting the backend's REAL
// authorization rules (core/scoping.py: is_company_admin / assert_can_manage_target;
// services/user.py: create_user_admin / update_user_admin; dependencies.py).
// There's no fine-grained per-resource permission: the real axes are is_superuser × role.
//
// The roles are NOT translated: they're the authorization model's names, the same
// ones shown in the table's Role column and used in the backend.
const ROLES = ["Member", "Company Admin", "Superuser"] as const;

// `key` indexes Capabilities.rows.*; the literal union (instead of string) is what
// lets tsc validate the key. The order is the matrix's reading order.
type CapabilityKey =
  | "ownProfile"
  | "otherUsers"
  | "listCompanyUsers"
  | "createUsers"
  | "editRole"
  | "toggleSuperuser"
  | "viewAudit"
  | "crossCompany";

const CAPABILITIES: { key: CapabilityKey; allowed: [boolean, boolean, boolean] }[] = [
  { key: "ownProfile", allowed: [true, true, true] },
  { key: "otherUsers", allowed: [false, false, true] },
  { key: "listCompanyUsers", allowed: [false, true, true] },
  { key: "createUsers", allowed: [false, true, true] },
  { key: "editRole", allowed: [false, true, true] },
  { key: "toggleSuperuser", allowed: [false, false, true] },
  { key: "viewAudit", allowed: [false, true, true] },
  { key: "crossCompany", allowed: [false, false, true] },
];

export function CapabilityLegend() {
  const t = useTranslations("Capabilities");

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <ShieldCheck size={16} className="text-fg-2" />
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        <span className="text-xs text-fg-3">{t("subtitle")}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">{t("capability")}</th>
              {ROLES.map((r) => (
                <th key={r} className="px-4 py-2 text-center font-medium">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CAPABILITIES.map((cap) => (
              <tr key={cap.key} className="border-t border-border">
                <td className="px-4 py-2 text-fg-2">{t(`rows.${cap.key}`)}</td>
                {cap.allowed.map((ok, i) => (
                  <td key={i} className="px-4 py-2 text-center">
                    {ok ? (
                      <Check size={15} className="mx-auto text-ok" />
                    ) : (
                      <Minus size={15} className="mx-auto text-fg-3" />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border px-4 py-2.5 text-[11.5px] text-fg-3">{t("note")}</p>
    </div>
  );
}
