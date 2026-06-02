"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getInstance } from "@/lib/api";
import { updateInstanceStatus, deleteInstance } from "@/lib/api";
import dynamic from "next/dynamic";
import { useMetrics } from "@/hooks/use-metrics";
import { Button } from "@/components/ui/button";
import type { Instance } from "@/lib/types";

// recharts não roda em SSR sob o Turbopack (usa `require` internamente).
// Carregamos o gráfico apenas no cliente (ssr: false) para evitar o
// "ReferenceError: require is not defined" durante a renderização no servidor.
const MetricsChart = dynamic(
  () => import("@/components/MetricsChart").then((m) => m.MetricsChart),
  { ssr: false }
);

export default function InstanceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [instance, setInstance] = useState<Instance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isActing, setIsActing] = useState(false);

  const { metrics } = useMetrics(id);

  useEffect(() => {
    getInstance(id)
      .then(setInstance)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load")
      )
      .finally(() => setIsLoading(false));
  }, [id]);

  // ─── Action handlers ────────────────────────────────────────────────────────

  async function handleStatusChange(action: "start" | "stop") {
    if (!instance) return;
    setIsActing(true);
    try {
      const updated = await updateInstanceStatus(instance.id, action);
      setInstance(updated); // React re-renders with new status automatically
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setIsActing(false);
    }
  }

  async function handleDelete() {
    if (!instance) return;
    // window.confirm() is the simplest way to ask for confirmation in the browser
    // Returns true if user clicked OK, false if clicked Cancel
    const confirmed = window.confirm(
      `Delete "${instance.name}"? This cannot be undone.`
    );
    if (!confirmed) return;

    setIsActing(true);
    try {
      await deleteInstance(instance.id);
      router.push("/"); // Navigate back to the list after deletion
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setIsActing(false);
    }
  }

  // ─── Loading / error states ──────────────────────────────────────────────────

  if (isLoading) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-zinc-500 text-sm">Loading...</p>
      </main>
    );
  }

  if (error || !instance) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-red-400 text-sm">{error ?? "Instance not found"}</p>
      </main>
    );
  }

  // ─── Derived state: which buttons to show ────────────────────────────────────
  // These are NOT stored in useState — they are recalculated on every render
  // from instance.status. When setInstance() is called, these update automatically.
  const canStart = instance.status === "stopped" || instance.status === "failed";
  const canStop = instance.status === "running";
  // Backend (soft_delete_instance) só permite deletar se NÃO estiver running.
  // Mantemos a UI alinhada: só liberamos Delete para stopped/failed.
  const canDelete = instance.status === "stopped" || instance.status === "failed";
  const isTransitioning = ["pending", "provisioning", "deleting"].includes(
    instance.status
  );

  return (
    <main className="flex flex-1 flex-col p-8 gap-6 max-w-2xl mx-auto w-full">
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          ← Back
        </button>
        <h1 className="text-xl font-semibold text-zinc-100">{instance.name}</h1>
        <span className="text-xs text-zinc-500 uppercase tracking-wide">
          {instance.status}
        </span>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900 divide-y divide-zinc-800">
        <Section title="Engine">
          <Row label="Version" value={`PostgreSQL ${instance.engine_version}`} />
          <Row label="Status" value={instance.status} />
        </Section>

        {(instance.host || instance.port || instance.db_name || instance.db_user) && (
          <Section title="Connection">
            {instance.host && <Row label="Host" value={instance.host} />}
            {instance.port && <Row label="Port" value={String(instance.port)} />}
            {instance.db_name && <Row label="Database" value={instance.db_name} />}
            {instance.db_user && <Row label="User" value={instance.db_user} />}
          </Section>
        )}

        {(instance.cpu || instance.memory_mb || instance.storage_gb) && (
          <Section title="Resources">
            {instance.cpu && <Row label="CPU" value={`${instance.cpu} vCPU`} />}
            {instance.memory_mb && (
              <Row label="Memory" value={`${instance.memory_mb / 1024} GB`} />
            )}
            {instance.storage_gb && (
              <Row label="Storage" value={`${instance.storage_gb} GB`} />
            )}
          </Section>
        )}

        {metrics && Object.keys(metrics.metrics).length > 0 && (
          <Section title="Metrics">
            <MetricsChart snapshot={metrics} />
            {Object.entries(metrics.metrics).map(([key, value]) => (
              <Row
                key={key}
                label={key.replace(/_/g, " ")}
                value={String(Number(value.toFixed(2)))}
              />
            ))}
          </Section>
        )}

        {instance.notes && (
          <Section title="Notes">
            <p className="px-4 py-3 text-sm text-zinc-400">{instance.notes}</p>
          </Section>
        )}

        {/* ─── Actions section ─────────────────────────────────────────────── */}
        {/* Only renders if instance is not already deleted */}
        {canDelete && (
          <Section title="Actions">
            <div className="px-4 py-3 flex items-center gap-3">

              {/* Start button: visible only when instance can be started */}
              {canStart && (
                <Button
                  onClick={() => handleStatusChange("start")}
                  disabled={isActing || isTransitioning}
                  className="bg-green-600 hover:bg-green-500 text-white"
                >
                  {isActing ? "Starting..." : "Start"}
                </Button>
              )}

              {/* Stop button: visible only when instance is running */}
              {canStop && (
                <Button
                  onClick={() => handleStatusChange("stop")}
                  disabled={isActing || isTransitioning}
                  variant="outline"
                  className="border-zinc-600 text-zinc-300 hover:bg-zinc-800"
                >
                  {isActing ? "Stopping..." : "Stop"}
                </Button>
              )}

              {/* Transitioning message: shows when status is in-progress */}
              {isTransitioning && (
                <p className="text-xs text-zinc-500">
                  {instance.status === "provisioning" && "Provisioning..."}
                  {instance.status === "pending" && "Pending..."}
                  {instance.status === "deleting" && "Deleting..."}
                </p>
              )}

              {/* Delete: always shown (except deleted/deleting), destructive */}
              <Button
                onClick={handleDelete}
                disabled={isActing || isTransitioning}
                variant="ghost"
                className="ml-auto text-red-400 hover:text-red-300 hover:bg-red-950/30"
              >
                Delete
              </Button>
            </div>
          </Section>
        )}
      </div>
    </main>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="px-4 pt-3 pb-1 text-xs font-medium text-zinc-500 uppercase tracking-wider">
        {title}
      </p>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <span className="text-sm text-zinc-500">{label}</span>
      <span className="text-sm text-zinc-100 font-mono">{value}</span>
    </div>
  );
}