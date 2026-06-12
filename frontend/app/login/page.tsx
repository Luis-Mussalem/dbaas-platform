"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";

// Classe compartilhada dos campos — evita repetir o estilo nos dois inputs.
const FIELD =
  "w-full rounded-md border border-border-strong bg-bg-2 px-3 py-2 text-sm text-foreground placeholder:text-fg-faint transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login } = useAuth();
  const router = useRouter();

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login(username, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha no login");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="relative flex min-h-screen flex-1 items-center justify-center overflow-hidden bg-bg px-4">
      {/* Brilho de marca sutil ao fundo (decorativo). */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 h-80 w-[36rem] -translate-x-1/2 rounded-full bg-brand opacity-[0.07] blur-3xl"
      />

      <div className="relative w-full max-w-sm">
        {/* Marca — mesma identidade da sidebar */}
        <div className="mb-6 flex items-center justify-center gap-2 text-[17px] font-semibold">
          <div className="flex h-7 w-7 items-center justify-center rounded-[8px] bg-primary text-[15px] font-bold text-primary-foreground">
            D
          </div>
          <span>DBaaS</span>
        </div>

        <div className="rounded-xl border border-border bg-surface p-7 shadow-sm">
          <div className="mb-5 space-y-1">
            <h1 className="text-lg font-semibold">Bem-vindo de volta</h1>
            <p className="text-sm text-fg-3">Acesse o painel da sua plataforma de bancos.</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="username" className="mb-1.5 block text-[13px] font-medium text-fg-2">
                Usuário
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className={FIELD}
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-[13px] font-medium text-fg-2">
                Senha
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className={FIELD}
              />
            </div>

            {error && (
              <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}

            <Button type="submit" disabled={isSubmitting} className="w-full">
              {isSubmitting ? "Entrando…" : "Entrar"}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs text-fg-faint">
          Plataforma de gestão de bancos PostgreSQL
        </p>
      </div>
    </main>
  );
}
