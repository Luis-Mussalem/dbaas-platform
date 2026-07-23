"use client";

import { useAnimatedNumber } from "@/hooks/use-animated-number";

// Renderiza um número que anima suavemente até `value` na transição. `format`
// recebe o valor já animado (ainda fracionário durante o percurso) e devolve a
// string exibida — normalmente `(n) => number(Math.round(n))`.
export function AnimatedNumber({
  value,
  format,
}: {
  value: number;
  format: (n: number) => string;
}) {
  const animated = useAnimatedNumber(value);
  return <>{format(animated)}</>;
}
