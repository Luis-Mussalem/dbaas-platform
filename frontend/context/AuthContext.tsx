"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { User } from "@/lib/types";
import { getCurrentUser, login as apiLogin, logout as apiLogout } from "@/lib/api";

// ─── Context shape ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  // Re-busca /auth/me e atualiza o `user` global. Chamado após editar o perfil
  // para que a Sidebar (e quem mais lê o contexto) reflita o novo email na hora.
  refreshUser: () => Promise<void>;
}

// ─── Context creation ──────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ─── Provider component ────────────────────────────────────────────────────────

interface AuthProviderProps {
  children: React.ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  // A sessão vive em cookies HttpOnly — JS não enxerga token nenhum. A única
  // fonte de verdade do "estou logado?" é o próprio backend, via /auth/me.
  const [user, setUser] = useState<User | null>(null);
  // Na /login não há sessão para hidratar — já inicia sem loading (o inicializador
  // lazy evita o setState síncrono no effect que o lint react-hooks proíbe).
  const [isLoading, setIsLoading] = useState(
    () => typeof window === "undefined" || window.location.pathname !== "/login"
  );

  useEffect(() => {
    // Na /login não há sessão para hidratar — evita um /me + refresh inúteis.
    if (window.location.pathname === "/login") return;

    let active = true;
    getCurrentUser()
      .then((u) => {
        if (active) setUser(u);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function login(username: string, password: string): Promise<void> {
    // O backend grava os cookies HttpOnly na resposta do login; em seguida
    // buscamos o usuário já autenticado por eles.
    await apiLogin(username, password);
    const u = await getCurrentUser();
    setUser(u);
  }

  async function refreshUser(): Promise<void> {
    const u = await getCurrentUser();
    setUser(u);
  }

  function logout(): void {
    // O backend blacklista os tokens e limpa os cookies na resposta; só então
    // navegamos, para o proxy já ver a sessão encerrada. Se a chamada falhar
    // (rede), navegamos mesmo assim — o usuário pediu para sair.
    apiLogout()
      .catch(() => undefined)
      .finally(() => {
        setUser(null);
        window.location.href = "/login";
      });
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

// ─── Consumer hook ─────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
