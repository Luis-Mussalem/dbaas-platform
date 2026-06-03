"use client";

import { useState } from "react";
import { Mail, KeyRound, Check, ShieldCheck } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { updateUser } from "@/lib/api";

const INPUT =
  "h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none transition focus:border-brand";
const BTN =
  "inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

// Pequeno aviso de sucesso/erro reutilizado pelos dois formulários.
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
  // `user` vem do AuthContext (estado global). `refreshUser` re-busca /auth/me
  // depois de salvar, para a Sidebar refletir o novo email na hora.
  const { user, refreshUser } = useAuth();

  // ── Formulário 1: email ──
  const [email, setEmail] = useState(user?.email ?? "");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailMsg, setEmailMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // ── Formulário 2: senha ── (independente do de email)
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [pwdBusy, setPwdBusy] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  if (!user) return <p className="text-sm text-fg-3">Carregando…</p>;

  async function saveEmail(e: React.FormEvent) {
    e.preventDefault(); // impede o reload padrão do <form> (controlamos via fetch)
    if (!user) return;
    if (!email.trim() || email === user.email) {
      setEmailMsg({ kind: "error", text: "Informe um email diferente do atual." });
      return;
    }
    setEmailBusy(true);
    setEmailMsg(null);
    try {
      await updateUser(user.id, { email: email.trim() });
      await refreshUser();
      setEmailMsg({ kind: "ok", text: "Email atualizado." });
    } catch (err) {
      setEmailMsg({ kind: "error", text: err instanceof Error ? err.message : "Falha ao salvar." });
    } finally {
      setEmailBusy(false);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (pwd.length < 8) {
      setPwdMsg({ kind: "error", text: "A senha deve ter ao menos 8 caracteres." });
      return;
    }
    if (pwd !== pwd2) {
      setPwdMsg({ kind: "error", text: "As senhas não coincidem." });
      return;
    }
    setPwdBusy(true);
    setPwdMsg(null);
    try {
      await updateUser(user.id, { password: pwd });
      setPwd("");
      setPwd2("");
      setPwdMsg({ kind: "ok", text: "Senha alterada." });
    } catch (err) {
      // O backend valida a força da senha; mostramos a mensagem dele tal qual.
      setPwdMsg({ kind: "error", text: err instanceof Error ? err.message : "Falha ao salvar." });
    } finally {
      setPwdBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Configurações</h1>
        <p className="mt-1 text-sm text-muted-foreground">Sua conta de operador.</p>
      </div>

      {/* ── Identidade da conta (somente leitura) ── */}
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
                  <ShieldCheck size={12} /> Superusuário
                </span>
              )}
              <span>
                membro desde {new Date(user.created_at).toLocaleDateString("pt-BR")}
              </span>
            </p>
          </div>
        </div>
      </div>

      {/* ── Trocar email ── */}
      <form onSubmit={saveEmail} className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <Mail size={15} className="text-fg-2" /> Email
        </h2>
        <p className="mb-3 text-xs text-fg-3">Usado para login e identificação.</p>
        <div className="flex flex-col gap-3 sm:max-w-md">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={INPUT}
            placeholder="voce@exemplo.com"
          />
          {emailMsg && <Notice kind={emailMsg.kind} text={emailMsg.text} />}
          <button type="submit" disabled={emailBusy} className={BTN}>
            {emailBusy ? "Salvando…" : "Salvar email"}
          </button>
        </div>
      </form>

      {/* ── Trocar senha ── */}
      <form onSubmit={savePassword} className="rounded-xl border border-border bg-surface p-5">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <KeyRound size={15} className="text-fg-2" /> Senha
        </h2>
        <p className="mb-3 text-xs text-fg-3">Mínimo de 8 caracteres.</p>
        <div className="flex flex-col gap-3 sm:max-w-md">
          <input
            type="password"
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            className={INPUT}
            placeholder="Nova senha"
            autoComplete="new-password"
          />
          <input
            type="password"
            value={pwd2}
            onChange={(e) => setPwd2(e.target.value)}
            className={INPUT}
            placeholder="Confirmar nova senha"
            autoComplete="new-password"
          />
          {pwdMsg && <Notice kind={pwdMsg.kind} text={pwdMsg.text} />}
          <button type="submit" disabled={pwdBusy} className={BTN}>
            {pwdBusy ? "Salvando…" : "Alterar senha"}
          </button>
        </div>
      </form>
    </div>
  );
}
