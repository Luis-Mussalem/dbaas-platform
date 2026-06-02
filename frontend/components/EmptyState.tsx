import type { ReactNode } from "react";
import { Construction } from "lucide-react";

// Estado vazio reutilizável — espelha o EmptyState do design.
export function EmptyState({
  title,
  subtitle,
  icon,
  action,
}: {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-border bg-bg-2 text-fg-3">
        {icon ?? <Construction size={24} />}
      </div>
      <h2 className="text-lg font-semibold">{title}</h2>
      {subtitle && <p className="max-w-sm text-sm text-muted-foreground">{subtitle}</p>}
      {action}
    </div>
  );
}
