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
      className="flex h-10 shrink-0 items-center gap-2.5 border-b border-info/25 bg-info/10 px-6 text-[13px] text-fg-2"
    >
      <Info size={15} className="shrink-0 text-info" />
      <span className="min-w-0 truncate">{t("message")}</span>
      <Link
        href="/demo"
        className="ml-auto shrink-0 font-medium text-info hover:underline"
      >
        {t("learnMore")}
      </Link>
    </div>
  );
}
