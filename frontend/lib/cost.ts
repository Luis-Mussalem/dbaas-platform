import type { Currency } from "@/i18n/config";
import type { Instance } from "@/lib/types";

// Monthly rates per currency. They are NOT an exchange-rate conversion: they're two
// independent price tables, the way cloud providers publish regional pricing in
// local currency. That's why the ratio between the two totals isn't an exchange rate.
// Illustrative values — an estimate derived from the specs, not real billing.
const RATES: Record<Currency, { vcpu: number; gbRam: number; gbStorage: number }> = {
  BRL: { vcpu: 60, gbRam: 20, gbStorage: 1.5 },
  USD: { vcpu: 12, gbRam: 4, gbStorage: 0.3 },
};

// Monthly cost estimate based on the specs.
// Reused by the Dashboard and the Instances page.
export function estimateMonthlyCost(instances: Instance[], currency: Currency): number {
  const rate = RATES[currency];
  return instances.reduce((sum, i) => {
    const cpu = (i.cpu ?? 0) * rate.vcpu;
    const ram = ((i.memory_mb ?? 0) / 1024) * rate.gbRam;
    const disk = (i.storage_gb ?? 0) * rate.gbStorage;
    return sum + cpu + ram + disk;
  }, 0);
}
