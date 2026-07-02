"use client";

import { Segmented } from "@/components/Segmented";
import { ENV_FILTERS, type EnvFilter } from "@/lib/environment";

// Barra de filtro de ambiente (Todos / produção / homologação / desenvolvimento).
// Fina camada sobre o Segmented alimentada pela fonte única lib/environment,
// para o Painel e a página de Instâncias compartilharem o mesmo controle.
export function EnvFilterBar({
  value,
  onChange,
  size = "sm",
}: {
  value: EnvFilter;
  onChange: (value: EnvFilter) => void;
  size?: "sm" | "md";
}) {
  return (
    <Segmented options={ENV_FILTERS} value={value} onChange={onChange} size={size} />
  );
}
