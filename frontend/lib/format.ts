// Helpers de formatação reutilizáveis (números e tempo).

// Bytes → string legível (KB/MB/GB/TB).
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  // 1 casa decimal só quando o número é pequeno (ex.: 1.5 GB), senão inteiro.
  return `${value.toFixed(value < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

// Número → string compacta com separador de milhar pt-BR (ex.: 1046 → "1.046").
export function formatNumber(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

// Valor em reais → "R$ 1.482" (sem centavos). Usado em estimativas de custo.
export function formatBRL(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  });
}

// Timestamp ISO → "há X" em português, relativo a agora.
export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return "agora";
  const min = Math.floor(sec / 60);
  if (min < 60) return `há ${min} min`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `há ${hr} h`;
  const day = Math.floor(hr / 24);
  return `há ${day} d`;
}
