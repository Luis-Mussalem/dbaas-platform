// Common (zero-based) ceiling for the cards' queries/s sparklines. With a SHARED
// scale, the line's height starts to encode magnitude — a 12 q/s card ends up
// visibly taller than a 4 q/s one — instead of each card auto-scaling and all of
// them looking equally full. Starts from the fleet's highest number, adds slack
// for the line's peaks (which oscillate above the average), and rounds to a "round"
// value, so the ceiling doesn't jump on every update.
export function qpsScaleMax(values: (number | null | undefined)[]): number {
  const peak = Math.max(0, ...values.map((v) => v ?? 0)) * 1.5;
  if (peak <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(peak));
  for (const step of [1, 2, 5, 10]) {
    if (peak <= step * mag) return step * mag;
  }
  return 10 * mag;
}
