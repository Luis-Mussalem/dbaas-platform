"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/AuthContext";
import { useUsers } from "@/hooks/use-users";
import { listCompanies } from "@/lib/api";
import { CreateUserDialog } from "@/components/CreateUserDialog";
import { StatCard } from "@/components/StatCard";
import { CapabilityLegend } from "@/components/CapabilityLegend";
import { useToast } from "@/context/ToastProvider";
import { cn } from "@/lib/utils";
import { useFormatters } from "@/hooks/use-formatters";
import type { Company } from "@/lib/types";
import { INPUT } from "@/lib/ui";

// Variante única desta página (h-7 com borda) — as compartilhadas estão em lib/ui.
const BTN_SM =
  "inline-flex h-7 items-center rounded-md border border-border px-2.5 text-[12px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-foreground disabled:opacity-50";

export default function AdminUsersPage() {
  const t = useTranslations("Employees");
  const tc = useTranslations("Common");
  const { ago } = useFormatters();
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

  // Só superuser pode listar empresas (403 para os demais) — evita chamada
  // inútil e permite tratar erro real com toast em vez de engoli-lo.
  // `toast` é memoizado no ToastProvider e `t` só muda ao trocar de idioma —
  // nenhum dos dois re-dispara o effect à toa.
  const isSuperuserMe = me?.is_superuser === true;
  useEffect(() => {
    if (!isSuperuserMe) return;
    listCompanies()
      .then(setCompanies)
      .catch((err) =>
        toast.error(err instanceof Error ? err.message : t("loadCompaniesFailed"))
      );
  }, [isSuperuserMe, toast, t]);

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

  // Métricas-resumo (client-side, sobre a lista já carregada).
  const adminCount = users.filter((u) => u.is_superuser || u.role === "admin").length;
  const lastActivityIso = users
    .map((u) => u.last_activity)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1);

  async function handleToggleActive(userId: string, currentlyActive: boolean) {
    try {
      await update(userId, { is_active: !currentlyActive });
      toast.success(currentlyActive ? t("toast.deactivated") : t("toast.reactivated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tc("error"));
    }
  }

  async function handleToggleSuperuser(userId: string, currentlySuperuser: boolean) {
    try {
      await update(userId, { is_superuser: !currentlySuperuser });
      toast.success(t("toast.updated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tc("error"));
    }
  }

  async function handleToggleRole(userId: string, currentRole: string) {
    try {
      const newRole = currentRole === "admin" ? "member" : "admin";
      await update(userId, { role: newRole });
      toast.success(t("toast.roleUpdated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tc("error"));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Users size={20} className="text-fg-2" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
          </div>
        </div>
        <CreateUserDialog companies={companies} onCreate={create} isSuperuser={isSuperuser} />
      </div>

      {/* métricas-resumo: total, donos/admins, atividade mais recente */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("stats.total")} value={users.length} sub={t("stats.totalSub")} />
        <StatCard
          label={t("stats.admins")}
          value={adminCount}
          sub={t("stats.adminsSub")}
          accent="ok"
        />
        <StatCard
          label={t("stats.lastActivity")}
          value={lastActivityIso ? ago(lastActivityIso) : tc("none")}
          sub={t("stats.lastActivitySub")}
        />
      </div>

      <CapabilityLegend />

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* filter bar */}
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          {isSuperuser && (
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-fg-3">
                {t("filters.company")}
              </span>
              <select
                value={filterCompanyId}
                onChange={(e) => setFilterCompanyId(e.target.value)}
                className={INPUT}
              >
                <option value="">{t("filters.allCompanies")}</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-fg-3">
              {t("filters.status")}
            </span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as typeof filterStatus)}
              className={INPUT}
            >
              <option value="all">{t("filters.all")}</option>
              <option value="active">{t("status.active")}</option>
              <option value="inactive">{t("status.inactive")}</option>
            </select>
          </label>
        </div>

        {/* table */}
        {isLoading ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{tc("loading")}</p>
        ) : error ? (
          <p className="px-4 py-8 text-center text-sm text-danger">{error}</p>
        ) : visible.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-fg-3">{t("empty")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
                <th className="px-4 py-2 font-medium">{t("table.email")}</th>
                <th className="px-4 py-2 font-medium">{t("table.company")}</th>
                <th className="px-4 py-2 font-medium">{t("table.role")}</th>
                <th className="px-4 py-2 font-medium">{t("table.status")}</th>
                <th className="px-4 py-2 font-medium">{t("table.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u) => (
                <tr key={u.id} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs text-foreground">{u.email}</td>
                  <td className="px-4 py-2 text-fg-2">
                    {u.company?.name ?? <span className="text-fg-3 italic">{tc("none")}</span>}
                  </td>
                  <td className="px-4 py-2">
                    {u.is_superuser ? (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] font-medium",
                          "border-info/25 bg-info/10 text-info"
                        )}
                      >
                        {t("roles.superuser")}
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
                        {u.role === "admin" ? t("roles.admin") : t("roles.member")}
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
                      {u.is_active ? t("status.active") : t("status.inactive")}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <button
                        className={BTN_SM}
                        disabled={u.id === me.id}
                        title={u.id === me.id ? t("selfDisabled") : undefined}
                        onClick={() => handleToggleActive(u.id, u.is_active)}
                      >
                        {u.is_active ? t("actions.deactivate") : t("actions.reactivate")}
                      </button>
                      {isSuperuser && (
                        <button
                          className={BTN_SM}
                          disabled={u.id === me.id}
                          title={u.id === me.id ? t("selfDisabled") : undefined}
                          onClick={() => handleToggleSuperuser(u.id, u.is_superuser)}
                        >
                          {u.is_superuser ? t("actions.demote") : t("actions.makeSuperuser")}
                        </button>
                      )}
                      {!u.is_superuser && (
                        <button
                          className={BTN_SM}
                          disabled={u.id === me.id}
                          title={u.id === me.id ? t("selfDisabled") : undefined}
                          onClick={() => handleToggleRole(u.id, u.role)}
                        >
                          {u.role === "admin" ? t("actions.makeMember") : t("actions.makeAdmin")}
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
