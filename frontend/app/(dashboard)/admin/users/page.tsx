"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Users } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useUsers } from "@/hooks/use-users";
import { listCompanies } from "@/lib/api";
import { CreateUserDialog } from "@/components/CreateUserDialog";
import { useToast } from "@/context/ToastProvider";
import { cn } from "@/lib/utils";
import type { Company } from "@/lib/types";

const INPUT =
  "h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground outline-none transition focus:border-brand";
const BTN_SM =
  "inline-flex h-7 items-center rounded-md border border-border px-2.5 text-[12px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:opacity-50";

export default function AdminUsersPage() {
  const router = useRouter();
  const { user: me } = useAuth();
  const { toast } = useToast();

  const [companies, setCompanies] = useState<Company[]>([]);
  const [filterCompanyId, setFilterCompanyId] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "active" | "inactive">("all");

  // Admin guard — redireciona usuário comum (não admin) antes de qualquer render visível.
  useEffect(() => {
    if (me && !me.is_superuser && me.role !== "admin") router.replace("/");
  }, [me, router]);

  useEffect(() => {
    listCompanies().then(setCompanies).catch(() => {});
  }, []);

  const { users, isLoading, error, create, update } = useUsers(
    filterCompanyId || undefined
  );

  // Retorna null (sem renderização) se não autenticado ou não admin
  if (!me || (me.is_superuser !== true && me.role !== "admin")) return null;

  const isSuperuser = me.is_superuser === true;

  const visible = users.filter((u) => {
    if (filterStatus === "active") return u.is_active;
    if (filterStatus === "inactive") return !u.is_active;
    return true;
  });

  async function handleToggleActive(userId: string, currentlyActive: boolean) {
    try {
      await update(userId, { is_active: !currentlyActive });
      toast.success(currentlyActive ? "User deactivated" : "User reactivated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    }
  }

  async function handleToggleSuperuser(userId: string, currentlySuperuser: boolean) {
    try {
      await update(userId, { is_superuser: !currentlySuperuser });
      toast.success("User updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    }
  }

  async function handleToggleRole(userId: string, currentRole: string) {
    try {
      const newRole = currentRole === "admin" ? "member" : "admin";
      await update(userId, { role: newRole });
      toast.success("Role updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Users size={20} className="text-fg-2" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Employees</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Manage platform users and their company assignments.
            </p>
          </div>
        </div>
        <CreateUserDialog companies={companies} onCreate={create} isSuperuser={isSuperuser} />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* filter bar */}
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          {isSuperuser && (
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">Company</span>
              <select
                value={filterCompanyId}
                onChange={(e) => setFilterCompanyId(e.target.value)}
                className={INPUT}
              >
                <option value="">All companies</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">Status</span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as typeof filterStatus)}
              className={INPUT}
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>

        {/* table */}
        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">Loading…</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : visible.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">No users found.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">Email</th>
                <th className="px-4 py-2 font-medium">Company</th>
                <th className="px-4 py-2 font-medium">Role</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u) => (
                <tr key={u.id} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs text-foreground">{u.email}</td>
                  <td className="px-4 py-2 text-fg-2">
                    {u.company?.name ?? <span className="text-fg-3 italic">—</span>}
                  </td>
                  <td className="px-4 py-2">
                    {u.is_superuser ? (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          "border-info/25 bg-info/10 text-info"
                        )}
                      >
                        Superuser
                      </span>
                    ) : (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          u.role === "admin"
                            ? "border-warning/25 bg-warning/10 text-warning"
                            : "border-border bg-surface-2 text-fg-2"
                        )}
                      >
                        {u.role === "admin" ? "Admin" : "Member"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                        u.is_active
                          ? "border-ok/25 bg-ok/10 text-ok"
                          : "border-danger/25 bg-danger/10 text-danger"
                      )}
                    >
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <button
                        className={BTN_SM}
                        disabled={u.id === me.id}
                        title={u.id === me.id ? "Cannot modify your own account here" : undefined}
                        onClick={() => handleToggleActive(u.id, u.is_active)}
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                      {isSuperuser && (
                        <button
                          className={BTN_SM}
                          disabled={u.id === me.id}
                          title={u.id === me.id ? "Cannot modify your own account here" : undefined}
                          onClick={() => handleToggleSuperuser(u.id, u.is_superuser)}
                        >
                          {u.is_superuser ? "Demote" : "Make superuser"}
                        </button>
                      )}
                      {!u.is_superuser && (
                        <button
                          className={BTN_SM}
                          disabled={u.id === me.id}
                          title={u.id === me.id ? "Cannot modify your own account here" : undefined}
                          onClick={() => handleToggleRole(u.id, u.role)}
                        >
                          {u.role === "admin" ? "Make member" : "Make admin"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
