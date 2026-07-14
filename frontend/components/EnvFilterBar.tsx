"use client";

import { useTranslations } from "next-intl";
import { Segmented } from "@/components/Segmented";
import { ENV_FILTER_VALUES, type EnvFilter } from "@/lib/environment";

// Barra de filtro de ambiente (Todos / produção / homologação / desenvolvimento).
// Fina camada sobre o Segmented: os VALORES vêm da fonte única lib/environment,
// os rótulos das mensagens — para o Painel e a página de Instâncias
// compartilharem o mesmo controle.
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
