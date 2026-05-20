"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { listInstances } from "@/lib/api";
import { InstanceCard } from "@/components/InstanceCard";
import type { Instance } from "@/lib/types";

export default function HomePage() {
  const [instances, setInstances] = useState<Instance[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { logout } = useAuth();

  useEffect(() => {
    listInstances()
      .then(setInstances)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setIsLoading(false));
  }, []);

  if (isLoading) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-zinc-500 text-sm">Loading...</p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-red-400 text-sm">{error}</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col p-8 gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-100">Instances</h1>
        <button
          onClick={logout}
          className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Sign out
        </button>
      </div>

      {instances.length === 0 ? (
        <p className="text-zinc-500 text-sm">No instances yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {instances.map((instance) => (
            <InstanceCard key={instance.id} instance={instance} />
          ))}
        </div>
      )}
    </main>
  );
}