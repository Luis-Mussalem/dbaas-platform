"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { User } from "@/lib/types";
import { getCurrentUser, login as apiLogin } from "@/lib/api";

// ─── Context shape ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
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
        setToken(null);
        setUser(null);
        setIsLoading(false);
      });
  }, [token]);

  async function login(username: string, password: string): Promise<void> {
    const response = await apiLogin(username, password);
    localStorage.setItem("access_token", response.access_token);
    setIsLoading(true);
    setToken(response.access_token);
  }

  function logout(): void {
    localStorage.removeItem("access_token");
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ token, user, isLoading, login, logout }}>
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