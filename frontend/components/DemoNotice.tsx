"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Info } from "lucide-react";

// Honest, always-visible banner: makes it clear the fleet (companies, traffic,
// and history) is generated on purpose so the platform can be fully explored —
// the product's core is managing instances that, without this, would be empty.
//
// Demo mode is baked into the build (`NEXT_PUBLIC_DEMO_MODE`, default "true"), like the
// API URL. On a real installation (DEMO_MODE=false) the banner doesn't appear.
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
