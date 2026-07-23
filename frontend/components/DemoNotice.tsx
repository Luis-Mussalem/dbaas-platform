"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Info } from "lucide-react";

// Faixa honesta, sempre visível: deixa claro que a frota (empresas, tráfego e
// histórico) é gerada de propósito para a plataforma poder ser explorada por
// inteiro — a base do produto é gerir instâncias que, sem isso, estariam vazias.
//
// Modo demo é baked no build (`NEXT_PUBLIC_DEMO_MODE`, default "true"), como a
// URL da API. Numa instalação real (DEMO_MODE=false) a faixa não aparece.
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE !== "false";

export function DemoNotice() {
  const t = useTranslations("DemoNotice");
  if (!DEMO_MODE) return null;

  return (
    <div
      role="note"
      className="flex min-h-[8vh] shrink-0 items-center gap-3.5 border-b border-info/25 bg-info/10 px-6 py-3"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-info/15 text-info">
        <Info size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-info">{t("title")}</p>
        <p className="text-[13px] leading-snug text-fg-2">{t("message")}</p>
      </div>
      <Link
        href="/demo"
        className="shrink-0 rounded-md border border-info/30 px-3 py-1.5 text-[13px] font-medium text-info transition-colors hover:bg-info/10"
      >
        {t("learnMore")}
      </Link>
    </div>
  );
}
