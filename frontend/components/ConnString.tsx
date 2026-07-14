"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("InstanceDetail.connString");
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  const uri = `postgresql://${user ?? "user"}:••••••••@${host}:${port ?? 5432}/${db ?? ""}`;

  function copy() {
    // Sucesso só depois que o clipboard confirmar — sem toast falso quando a
    // cópia falha (clipboard indisponível fora de HTTPS/localhost, permissão).
    if (!navigator.clipboard) {
      toast.error(t("copyUnavailable"));
      return;
    }
    navigator.clipboard
      .writeText(uri)
      .then(() => {
        setCopied(true);
        toast.success(t("copied"));
        setTimeout(() => setCopied(false), 1400);
      })
      .catch(() => toast.error(t("copyFailed")));
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
        {t("label")}
      </span>
      <div className="flex items-center gap-2 rounded-md border border-border bg-bg-2 px-3 py-2 font-mono text-xs text-fg-2">
        <span className="flex-1 truncate">{uri}</span>
        <button
          onClick={copy}
          title={t("copy")}
          className="flex h-6 w-6 items-center justify-center rounded text-fg-3 transition-colors hover:bg-surface-2 hover:text-foreground"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
      <span className="text-[11px] text-fg-3">{t("note")}</span>
    </div>
  );
}
