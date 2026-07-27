import { cn } from "@/lib/utils";

// Pulsing loading block — the base for page skeletons.
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-2", className)}
    />
  );
}
