"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Copy, Check } from "lucide-react";
import { useToast } from "@/context/ToastProvider";

// The instance's connection string. The host/port/database/user fields are real
// (come from GET /instances/{id}); the PASSWORD is encrypted on the backend and never
// returned by the API — that's why it shows up masked. It's informational, not a "ready" copy.
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
    // Success only after the clipboard confirms — no false toast when the
    // copy fails (clipboard unavailable outside HTTPS/localhost, permission).
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
