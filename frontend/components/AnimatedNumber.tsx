"use client";

import { useAnimatedNumber } from "@/hooks/use-animated-number";

// Renders a number that smoothly animates up to `value` on transition. `format`
// receives the already-animated value (still fractional mid-transition) and returns
// the displayed string — typically `(n) => number(Math.round(n))`.
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
