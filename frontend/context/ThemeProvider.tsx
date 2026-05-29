"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// ─── Tipos ──────────────────────────────────────────────────────────────────

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

// ─── Context ─────────────────────────────────────────────────────────────────

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "theme";

// Lê o tema salvo no localStorage; default "dark" (igual ao design).
// Protegido contra SSR: no servidor não existe `window`.
function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === "light" || saved === "dark" ? saved : "dark";
}

// ─── Provider ────────────────────────────────────────────────────────────────

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Lazy initializer: getStoredTheme roda UMA vez, no primeiro render.
  // No servidor retorna "dark" (não há localStorage); no cliente lê a
  // preferência salva. Como nenhum JSX depende de `theme` (a classe vai
  // direto na <html> pelo effect abaixo), não há divergência de hidratação.
  const [theme, setTheme] = useState<Theme>(getStoredTheme);

  // Sincroniza o estado do React com o DOM (uso correto de useEffect):
  // aplica/remove a classe `dark` na <html> e persiste a escolha.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.setAttribute("data-dir", "habitat");
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value: ThemeContextValue = {
    theme,
    setTheme,
    toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

// ─── Hook consumidor ──────────────────────────────────────────────────────────

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return ctx;
}