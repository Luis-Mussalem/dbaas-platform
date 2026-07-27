import { Skeleton } from "@/components/ui/skeleton";

// Dashboard/Instances skeleton while the data loads: mirrors the KPI row
// (4 tiles) and the card grid, so the layout doesn't "jump" when the data arrives.
export function FleetSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      {/* Header: title + actions */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-7 w-40" />
          <Skeleton className="h-4 w-56" />
        </div>
        <Skeleton className="h-9 w-32" />
      </div>

      {/* KPI row (same grid as FleetKpiRow) */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
          >
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-7 w-16" />
          </div>
        ))}
      </div>

      {/* Card grid (same grid as the pages) */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: cards }).map((_, i) => (
          <div
            key={i}
            className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4"
          >
            <div className="flex items-center gap-2.5">
              <Skeleton className="h-2 w-2 rounded-full" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="ml-auto h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="h-10 w-full" />
            <div className="flex gap-2">
              <Skeleton className="h-3.5 w-20" />
              <Skeleton className="h-3.5 w-16" />
              <Skeleton className="ml-auto h-3.5 w-12" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
