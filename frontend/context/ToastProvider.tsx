"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";

// ─── Tipos ──────────────────────────────────────────────────────────────────

type Variant = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  variant: Variant;
}

// API exposta aos componentes: três atalhos por tipo de mensagem.
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

const DURATION_MS = 4500; // tempo até sumir sozinho

// Estilo por variante: ícone + cor semântica (tokens do tema).
const TONE: Record<Variant, { icon: typeof Info; className: string }> = {
  success: { icon: CheckCircle2, className: "text-ok" },
  error: { icon: AlertCircle, className: "text-danger" },
  info: { icon: Info, className: "text-info" },
};

// ─── Provider ────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Contador de ids estável entre renders (não precisa causar re-render).
  const nextId = useRef(0);

  const remove = useCallback((id: number) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
  }, []);

  // Cria um toast e agenda sua remoção automática.
  const push = useCallback(
    (variant: Variant, message: string) => {
      const id = nextId.current++;
      setToasts((cur) => [...cur, { id, message, variant }]);
      setTimeout(() => remove(id), DURATION_MS);
    },
    [remove],
  );

  // `toast` é estável (useRef) — componentes podem usá-lo em effects sem
  // recriá-lo a cada render.
  const apiRef = useRef<ToastApi>({
    success: (m) => push("success", m),
    error: (m) => push("error", m),
    info: (m) => push("info", m),
  });
  // Mantém os closures apontando para o `push` atual.
  apiRef.current = {
    success: (m) => push("success", m),
    error: (m) => push("error", m),
    info: (m) => push("info", m),
  };

  return (
    <ToastContext.Provider value={{ toast: apiRef.current }}>
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
                aria-label="Fechar"
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
