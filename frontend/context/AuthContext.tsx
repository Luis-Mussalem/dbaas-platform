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
  // Re-fetches /auth/me and updates the global `user`. Called after editing the profile
  // so the Sidebar (and whoever else reads the context) reflects the new email right away.
  refreshUser: () => Promise<void>;
}

// ─── Context creation ──────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ─── Provider component ────────────────────────────────────────────────────────

interface AuthProviderProps {
  children: React.ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  // The session lives in HttpOnly cookies — JS can't see any token. The only
  // source of truth for "am I logged in?" is the backend itself, via /auth/me.
  const [user, setUser] = useState<User | null>(null);
  // On /login there's no session to hydrate — it starts without loading right away (the lazy
  // initializer avoids the synchronous setState in the effect that the react-hooks lint forbids).
  const [isLoading, setIsLoading] = useState(
    () => typeof window === "undefined" || window.location.pathname !== "/login"
  );

  useEffect(() => {
    // On /login there's no session to hydrate — avoids a useless /me + refresh.
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
    // The backend writes the HttpOnly cookies in the login response; we then
    // fetch the now-authenticated user via them.
    await apiLogin(username, password);
    const u = await getCurrentUser();
    setUser(u);
  }

  async function refreshUser(): Promise<void> {
    const u = await getCurrentUser();
    setUser(u);
  }

  function logout(): void {
    // The backend blacklists the tokens and clears the cookies in the response; only then
    // do we navigate, so the proxy already sees the session ended. If the call fails
    // (network), we navigate anyway — the user asked to log out.
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
