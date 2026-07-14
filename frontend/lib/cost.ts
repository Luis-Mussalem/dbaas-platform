import type { Currency } from "@/i18n/config";
import type { Instance } from "@/lib/types";

// Tarifas mensais por moeda. NÃO são conversão por câmbio: são duas tabelas de
// preço independentes, como provedores de nuvem publicam preço regional em
// moeda local. Por isso a razão entre os dois totais não é uma cotação.
// Valores ilustrativos — estimativa derivada das specs, não faturamento real.
const RATES: Record<Currency, { vcpu: number; gbRam: number; gbStorage: number }> = {
  BRL: { vcpu: 60, gbRam: 20, gbStorage: 1.5 },
  USD: { vcpu: 12, gbRam: 4, gbStorage: 0.3 },
};

// Estimativa de custo mensal a partir das specs.
// Reusado pelo Painel e pela página de Instâncias.
export function estimateMonthlyCost(instances: Instance[], currency: Currency): number {
  const rate = RATES[currency];
  return instances.reduce((sum, i) => {
    const cpu = (i.cpu ?? 0) * rate.vcpu;
    const ram = ((i.memory_mb ?? 0) / 1024) * rate.gbRam;
    const disk = (i.storage_gb ?? 0) * rate.gbStorage;
    return sum + cpu + ram + disk;
  }, 0);
}
