"use client";

import { useState } from "react";
import { Mail, KeyRound, Check, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/AuthContext";
import { updateUser } from "@/lib/api";
import { useFormatters } from "@/hooks/use-formatters";
import { BTN_PRIMARY, INPUT_LG } from "@/lib/ui";

// Small success/error notice reused by both forms.
function Notice({ kind, text }: { kind: "ok" | "error"; text: string }) {
  return (
    <div
      className={
        kind === "ok"
          ? "flex items-center gap-1.5 rounded-md border border-ok/30 bg-ok/10 px-3 py-2 text-sm text-ok"
          : "rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
      }
    >
      {kind === "ok" && <Check size={14} />}
      {text}
    </div>
  );
}

export default function SettingsPage() {
  const t = useTranslations("Settings");
  const tc = useTranslations("Common");
  const { dateTime } = useFormatters();
  // `user` comes from AuthContext (global state). `refreshUser` re-fetches /auth/me
  // after saving, so the Sidebar reflects the new email right away.
  const { user, refreshUser } = useAuth();

  // Both forms ask for the CURRENT password. Email and password are the account's
  // recovery handles, so the backend requires re-authentication to change either
  // (see the UserUpdate schema): a stolen session must not convert into permanent
  // ownership of the account. Each form keeps its own field — they are independent
  // and neither should leave a credential sitting in the other's state.

  // ── Form 1: email ──
  const [email, setEmail] = useState(user?.email ?? "");
  const [emailPwd, setEmailPwd] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailMsg, setEmailMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // ── Form 2: password ── (independent from the email one)
  const [currentPwd, setCurrentPwd] = useState("");
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [pwdBusy, setPwdBusy] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  if (!user) return <p className="text-sm text-fg-3">{tc("loading")}</p>;

  async function saveEmail(e: React.FormEvent) {
    e.preventDefault(); // prevents the <form>'s default reload (we control it via fetch)
    if (!user) return;
    if (!email.trim() || email === user.email) {
      setEmailMsg({ kind: "error", text: t("email.sameAsCurrent") });
      return;
    }
    if (!emailPwd) {
      setEmailMsg({ kind: "error", text: t("currentPasswordRequired") });
      return;
    }
    setEmailBusy(true);
    setEmailMsg(null);
    try {
      await updateUser(user.id, { email: email.trim(), current_password: emailPwd });
      await refreshUser();
      // Clear the credential as soon as it has served its purpose — it should not
      // linger in component state after the request.
      setEmailPwd("");
      setEmailMsg({ kind: "ok", text: t("email.updated") });
    } catch (err) {
      setEmailMsg({ kind: "error", text: err instanceof Error ? err.message : t("saveFailed") });
    } finally {
      setEmailBusy(false);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (pwd.length < 12) {
      setPwdMsg({ kind: "error", text: t("password.tooShort") });
      return;
    }
    if (pwd !== pwd2) {
      setPwdMsg({ kind: "error", text: t("password.mismatch") });
      return;
    }
    if (!currentPwd) {
      setPwdMsg({ kind: "error", text: t("currentPasswordRequired") });
      return;
    }
    setPwdBusy(true);
    setPwdMsg(null);
    try {
      await updateUser(user.id, { password: pwd, current_password: currentPwd });
      setCurrentPwd("");
      setPwd("");
      setPwd2("");
      setPwdMsg({ kind: "ok", text: t("password.updated") });
    } catch (err) {
      // The backend validates password strength; we show its message as-is.
      setPwdMsg({ kind: "error", text: err instanceof Error ? err.message : t("saveFailed") });
    } finally {
      setPwdBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* ── Account identity (read-only) ── */}
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-base font-semibold text-primary-foreground">
            {user.email.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium text-foreground">{user.email}</p>
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-3">
              {user.is_superuser && (
                <span className="inline-flex items-center gap-1 text-info">
                  <ShieldCheck size={12} /> {t("superuser")}
                </span>
              )}
              <span>{t("memberSince", { date: dateTime(user.created_at, "date") })}</span>
            </p>
          </div>
        </div>
      </div>

      {/* ── Change email ── */}
      <form onSubmit={saveEmail} className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <Mail size={15} className="text-fg-2" /> {t("email.title")}
        </h2>
        <p className="mb-3 text-xs text-fg-3">{t("email.hint")}</p>
        <div className="flex flex-col gap-3 sm:max-w-md">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={INPUT_LG}
            placeholder={t("email.placeholder")}
          />
          <input
            type="password"
            value={emailPwd}
            onChange={(e) => setEmailPwd(e.target.value)}
            className={INPUT_LG}
            placeholder={t("email.currentPasswordPlaceholder")}
            autoComplete="current-password"
          />
          <p className="text-xs text-fg-3">{t("email.reauthHint")}</p>
          {emailMsg && <Notice kind={emailMsg.kind} text={emailMsg.text} />}
          <button type="submit" disabled={emailBusy} className={BTN_PRIMARY}>
            {emailBusy ? tc("saving") : t("email.save")}
          </button>
        </div>
      </form>

      {/* ── Change password ── */}
      <form onSubmit={savePassword} className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <KeyRound size={15} className="text-fg-2" /> {t("password.title")}
        </h2>
        <p className="mb-3 text-xs text-fg-3">{t("password.hint")}</p>
        <div className="flex flex-col gap-3 sm:max-w-md">
          <input
            type="password"
            value={currentPwd}
            onChange={(e) => setCurrentPwd(e.target.value)}
            className={INPUT_LG}
            placeholder={t("password.currentPasswordPlaceholder")}
            autoComplete="current-password"
          />
          <input
            type="password"
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            className={INPUT_LG}
            placeholder={t("password.placeholder")}
            autoComplete="new-password"
          />
          <input
            type="password"
            value={pwd2}
            onChange={(e) => setPwd2(e.target.value)}
            className={INPUT_LG}
            placeholder={t("password.confirmPlaceholder")}
            autoComplete="new-password"
          />
          <p className="text-xs text-fg-3">{t("password.reauthHint")}</p>
          {pwdMsg && <Notice kind={pwdMsg.kind} text={pwdMsg.text} />}
          <button type="submit" disabled={pwdBusy} className={BTN_PRIMARY}>
            {pwdBusy ? tc("saving") : t("password.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
