import { useEffect, useRef, useState } from "react";

// Animates a number between two MEASURED values on transition, so an update
// arriving every 15s "walks" smoothly instead of jumping — the fleet looks alive
// without inventing data (it only interpolates the visual between two real readings).
//
// `currentRef` holds the value displayed on each frame: a new target arriving
// mid-animation starts from where the number currently is, not from a jump.
export function useAnimatedNumber(target: number, durationMs = 400): number {
  const [display, setDisplay] = useState(target);
  const currentRef = useRef(target);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const from = currentRef.current;
    if (from === target) return;

    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
      const value = from + (target - from) * eased;
      currentRef.current = value;
      setDisplay(value);
      if (progress < 1) frameRef.current = requestAnimationFrame(step);
    };

    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [target, durationMs]);

  return display;
}
