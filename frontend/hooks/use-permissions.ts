"use client";

import { useAuth } from "@/context/AuthContext";

/**
 * Mirrors the backend's write gate: members observe, admins operate.
 *
 * Every state-changing endpoint depends on `get_current_company_admin`
 * (backend/src/core/dependencies.py); everything read-only is open to any member
 * of the company. This hook is the UI half of that same rule — it decides which
 * controls are worth showing, and nothing more.
 *
 * It is NOT the enforcement. The server refuses a member's DELETE whether or not
 * a button was rendered; hiding it only spares the user a control that would
 * answer 403. Treat a change here as cosmetic and the backend dependency as the
 * security boundary — never the reverse.
 */
export function useCanManage(): boolean {
  const { user } = useAuth();
  if (!user) return false;
  return user.is_superuser || user.role === "admin";
}
