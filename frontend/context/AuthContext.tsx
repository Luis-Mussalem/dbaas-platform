"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { User } from "@/lib/types";
import { getCurrentUser, login as apiLogin, logout as apiLogout } from "@/lib/api";

// ─── Context shape ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  token: string | null;
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
  const [token, setToken] = useState<string | null>(() =>
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null
  );
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(
    () => typeof window !== "undefined" && !!localStorage.getItem("access_token")
  );

  useEffect(() => {
    if (!token) return;

    getCurrentUser()
      .then((u) => {
        setUser(u);
        setIsLoading(false);
      })
      .catch(() => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        document.cookie = "auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
        setToken(null);
        setUser(null);
        setIsLoading(false);
      });
  }, [token]);

  async function login(username: string, password: string): Promise<void> {
    const response = await apiLogin(username, password);
    localStorage.setItem("access_token", response.access_token);
    localStorage.setItem("refresh_token", response.refresh_token);
    document.cookie = `auth_token=${response.access_token}; path=/; SameSite=Lax`;
    setIsLoading(true);
    setToken(response.access_token);
  }

  async function refreshUser(): Promise<void> {
    const u = await getCurrentUser();
    setUser(u);
  }

  function logout(): void {
    const refreshToken = localStorage.getItem("refresh_token");
    // Fire-and-forget: blacklist tokens on backend (best-effort, never blocks UI)
    apiLogout(refreshToken).catch(() => undefined);
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    document.cookie = "auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ token, user, isLoading, login, logout, refreshUser }}>
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