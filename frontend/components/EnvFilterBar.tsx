"use client";

import { useTranslations } from "next-intl";
import { Segmented } from "@/components/Segmented";
import { ENV_FILTER_VALUES, type EnvFilter } from "@/lib/environment";

// Environment filter bar (All / production / staging / development).
// A thin layer over Segmented: the VALUES come from the single source lib/environment,
// the labels from the messages — so the Dashboard and the Instances page
// share the same control.
export function EnvFilterBar({
  value,
  onChange,
  size = "sm",
}: {
  value: EnvFilter;
  onChange: (value: EnvFilter) => void;
  size?: "sm" | "md";
}) {
  const t = useTranslations("Environments");
  const options = ENV_FILTER_VALUES.map((v) => ({ value: v, label: t(v) }));

  return <Segmented options={options} value={value} onChange={onChange} size={size} />;
}
