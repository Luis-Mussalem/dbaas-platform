"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/context/ToastProvider";
import type { Company, UserAdminCreate, UserRole } from "@/lib/types";

interface CreateUserDialogProps {
  companies: Company[];
  onCreate: (data: UserAdminCreate) => Promise<void>;
  isSuperuser: boolean;
}

export function CreateUserDialog({ companies, onCreate, isSuperuser: isCurrentUserSuperuser }: CreateUserDialogProps) {
  const t = useTranslations("Employees.dialog");
  const tr = useTranslations("Employees.roles");
  const tt = useTranslations("Employees.toast");
  const tc = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [role, setRole] = useState<UserRole>("member");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  // Company admin (not superuser) can only create members and admins for their own company
  const canCreateSuperuser = isCurrentUserSuperuser;
  const canChooseCompany = isCurrentUserSuperuser;
  const canChooseRole = !isCurrentUserSuperuser;

  function reset() {
    setEmail("");
    setPassword("");
    setCompanyId("");
    setIsSuperuser(false);
    setRole("member");
    setError(null);
  }

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const payload: UserAdminCreate = {
        email,
        password,
        is_superuser: isSuperuser,
        ...(companyId ? { company_id: companyId } : {}),
        ...(canChooseRole ? { role } : {}),
      };
      await onCreate(payload);
      toast.success(tt("created"));
      reset();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("createFailed"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset(); }}>
      <DialogTrigger render={<Button />}>
        {t("title")}
      </DialogTrigger>
      <DialogContent className="bg-zinc-900 border-zinc-800">
        <DialogHeader>
          <DialogTitle className="text-zinc-100">{t("title")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 mt-2">
          <div className="space-y-1">
            <label htmlFor="cu-email" className="text-sm text-zinc-400">{t("email")}</label>
            <input
              id="cu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder={t("emailPlaceholder")}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="cu-password" className="text-sm text-zinc-400">{t("password")}</label>
            <input
              id="cu-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder={t("passwordPlaceholder")}
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
          </div>

          {canChooseCompany && (
            <div className="space-y-1">
              <label htmlFor="cu-company" className="text-sm text-zinc-400">
                {t("companyLabel", { superuser: String(isSuperuser) })}
              </label>
              <select
                id="cu-company"
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
                required={!isSuperuser}
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-500"
              >
                <option value="">{t("selectCompany")}</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          )}

          {canCreateSuperuser && (
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isSuperuser}
                onChange={(e) => setIsSuperuser(e.target.checked)}
                className="accent-blue-500"
              />
              <span className="text-sm text-zinc-400">{t("superuser")}</span>
            </label>
          )}

          {canChooseRole && (
            <div className="space-y-1">
              <label htmlFor="cu-role" className="text-sm text-zinc-400">{t("role")}</label>
              <select
                id="cu-role"
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-500"
              >
                <option value="member">{tr("member")}</option>
                <option value="admin">{tr("admin")}</option>
              </select>
            </div>
          )}

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => { setOpen(false); reset(); }}
              className="text-zinc-400 hover:text-zinc-100"
            >
              {tc("cancel")}
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? t("creating") : t("create")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
