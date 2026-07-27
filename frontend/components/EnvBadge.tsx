"use client";

import { useTranslations } from "next-intl";
import type { Environment } from "@/lib/types";
import { environmentTone } from "@/lib/environment";

// Environment tag: translated label + semantic color, derived from the single
// source lib/environment. Only the tone's Tailwind classes live here (the rest is
// shared). Null environment → renders nothing.
const TONE_CLS: Record<"ok" | "warn" | "info", string> = {
  ok: "text-ok border-ok/25 bg-ok/10",
  warn: "text-warn border-warn/25 bg-warn/10",
  info: "text-info border-info/25 bg-info/10",
};

export function EnvBadge({ environment }: { environment: Environment | null }) {
  const t = useTranslations("Environments");
  if (!environment) return null;
  const tone = environmentTone(environment);
  if (!tone) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE_CLS[tone]}`}
    >
      {t(environment)}
    </span>
  );
}
