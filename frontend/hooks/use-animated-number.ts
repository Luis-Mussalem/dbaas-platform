import { useEffect, useRef, useState } from "react";

// Anima um número entre dois valores MEDIDOS na transição, para uma atualização
// que chega a cada 15s "andar" suavemente em vez de saltar — a frota parece viva
// sem inventar dado (interpola só o visual entre duas leituras reais).
//
// `currentRef` guarda o valor exibido a cada frame: uma nova meta que chegue no
// meio da animação parte de onde o número está, não de um salto.
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
