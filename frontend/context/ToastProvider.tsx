"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";

// ─── Tipos ──────────────────────────────────────────────────────────────────

type Variant = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  variant: Variant;
}

// API exposed to components: three shortcuts by message type.
interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

interface ToastContextValue {
  toast: ToastApi;
}

// ─── Context ─────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

const DURATION_MS = 4500; // time until it disappears on its own

// Style per variant: icon + semantic color (theme tokens).
const TONE: Record<Variant, { icon: typeof Info; className: string }> = {
  success: { icon: CheckCircle2, className: "text-ok" },
  error: { icon: AlertCircle, className: "text-danger" },
  info: { icon: Info, className: "text-info" },
};

// ─── Provider ────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const tc = useTranslations("Common");
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Id counter stable across renders (doesn't need to cause a re-render).
  const nextId = useRef(0);

  const remove = useCallback((id: number) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
  }, []);

  // Creates a toast and schedules its automatic removal.
  const push = useCallback(
    (variant: Variant, message: string) => {
      const id = nextId.current++;
      setToasts((cur) => [...cur, { id, message, variant }]);
      setTimeout(() => remove(id), DURATION_MS);
    },
    [remove],
  );

  const toast = useMemo<ToastApi>(
    () => ({
      success: (m) => push("success", m),
      error: (m) => push("error", m),
      info: (m) => push("info", m),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}

      {/* Pilha de toasts — fixa no canto inferior direito. */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => {
          const { icon: Icon, className } = TONE[t.variant];
          return (
            <div
              key={t.id}
              className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-border bg-surface px-3.5 py-3 shadow-lg animate-in slide-in-from-bottom-2 fade-in"
              role="status"
            >
              <Icon size={16} className={`mt-0.5 shrink-0 ${className}`} />
              <p className="flex-1 text-[13px] leading-snug text-fg-2">{t.message}</p>
              <button
                onClick={() => remove(t.id)}
                className="shrink-0 text-fg-faint transition-colors hover:text-foreground"
                aria-label={tc("close")}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

// ─── Hook consumidor ──────────────────────────────────────────────────────────

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}
