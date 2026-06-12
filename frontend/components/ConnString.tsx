"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { useToast } from "@/context/ToastProvider";

// String de conexão da instância. Os campos host/porta/banco/usuário são reais
// (vêm do GET /instances/{id}); a SENHA é cifrada no backend e nunca devolvida
// pela API — por isso aparece mascarada. É informativa, não copiável "pronta".
export function ConnString({
  host,
  port,
  db,
  user,
}: {
  host: string;
  port: number | null;
  db: string | null;
  user: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  const uri = `postgresql://${user ?? "user"}:••••••••@${host}:${port ?? 5432}/${db ?? ""}`;

  function copy() {
    navigator.clipboard?.writeText(uri).catch(() => {});
    setCopied(true);
    toast.success("String de conexão copiada.");
    setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
        String de conexão
      </span>
      <div className="flex items-center gap-2 rounded-md border border-border bg-bg-2 px-3 py-2 font-mono text-xs text-fg-2">
        <span className="flex-1 truncate">{uri}</span>
        <button
          onClick={copy}
          title="Copiar"
          className="flex h-6 w-6 items-center justify-center rounded text-fg-3 transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
      <span className="text-[11px] text-fg-3">
        A senha é cifrada e não é exposta pela API.
      </span>
    </div>
  );
}
