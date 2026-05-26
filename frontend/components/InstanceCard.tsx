import { cn } from "@/lib/utils";
import type { Instance, InstanceStatus } from "@/lib/types";

// ─── Status badge styles ───────────────────────────────────────────────────────

const STATUS_STYLES: Record<InstanceStatus, string> = {
  running:      "bg-green-500/10 text-green-400",
  stopped:      "bg-zinc-500/10 text-zinc-400",
  pending:      "bg-yellow-500/10 text-yellow-400",
  provisioning: "bg-blue-500/10 text-blue-400",
  deleting:     "bg-red-500/10 text-red-400",
  deleted:      "bg-zinc-700/20 text-zinc-500",
  failed:       "bg-red-700/10 text-red-500",
};

// ─── Props ─────────────────────────────────────────────────────────────────────

interface InstanceCardProps {
  instance: Instance;
  onClick?: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function InstanceCard({ instance, onClick }: InstanceCardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "rounded-lg border border-zinc-800 bg-zinc-900 p-4",
        onClick && "cursor-pointer hover:border-zinc-700 transition-colors"
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="font-medium text-zinc-100 truncate">{instance.name}</p>
          <p className="text-sm text-zinc-500 mt-0.5">
            PostgreSQL {instance.engine_version}
            {instance.host && ` · ${instance.host}:${instance.port}`}
          </p>
        </div>

        <span
          className={cn(
            "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium uppercase tracking-wide",
            STATUS_STYLES[instance.status]
          )}
        >
          {instance.status}
        </span>
      </div>

      {(instance.cpu || instance.memory_mb || instance.storage_gb) && (
        <div className="flex gap-4 mt-3 pt-3 border-t border-zinc-800">
          {instance.cpu && (
            <p className="text-xs text-zinc-500">{instance.cpu} vCPU</p>
          )}
          {instance.memory_mb && (
            <p className="text-xs text-zinc-500">{instance.memory_mb / 1024} GB RAM</p>
          )}
          {instance.storage_gb && (
            <p className="text-xs text-zinc-500">{instance.storage_gb} GB disk</p>
          )}
        </div>
      )}
    </div>
  );
}