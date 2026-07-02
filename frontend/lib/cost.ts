import type { Instance } from "@/lib/types";

// Estimativa de custo mensal a partir das specs (derivado, NÃO faturamento real).
// Tarifas ilustrativas em BRL/mês — apenas para dar concretude ao card "Gasto".
// Extraído para ser reusado pelo Painel e pela página de Instâncias.
export function estimateMonthlyCost(instances: Instance[]): number {
  const PER_VCPU = 60;
  const PER_GB_RAM = 20;
  const PER_GB_STORAGE = 1.5;
  return instances.reduce((sum, i) => {
    const cpu = (i.cpu ?? 0) * PER_VCPU;
    const ram = ((i.memory_mb ?? 0) / 1024) * PER_GB_RAM;
    const disk = (i.storage_gb ?? 0) * PER_GB_STORAGE;
    return sum + cpu + ram + disk;
  }, 0);
}
