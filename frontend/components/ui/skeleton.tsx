import { cn } from "@/lib/utils";

// Bloco de carregamento pulsante — base para os esqueletos de página.
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-2", className)}
    />
  );
}
