import { useEffect, useState } from "react";
import {
  createInstance,
  deleteInstance,
  listInstances,
  updateInstanceStatus,
} from "@/lib/api";
import type { Instance, InstanceCreate } from "@/lib/types";

// ─── Return type ───────────────────────────────────────────────────────────────

interface UseInstancesResult {
  instances: Instance[];
  isLoading: boolean;
  error: string | null;
  create: (data: InstanceCreate) => Promise<void>;
  updateStatus: (id: string, action: "start" | "stop") => Promise<Instance>;
  remove: (id: string) => Promise<void>;
}

// ─── Hook ──────────────────────────────────────────────────────────────────────

export function useInstances(): UseInstancesResult {
  const [instances, setInstances] = useState<Instance[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch all instances once on mount
  useEffect(() => {
    listInstances()
      .then(setInstances)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setIsLoading(false));
  }, []);

  // Add new instance to the local list after creation
  async function create(data: InstanceCreate): Promise<void> {
    const instance = await createInstance(data);
    setInstances((prev) => [...prev, instance]);
  }

  // Update status of one instance in the local list
  // Returns the updated instance so the detail page can set its own state
  async function updateStatus(id: string, action: "start" | "stop"): Promise<Instance> {
    const updated = await updateInstanceStatus(id, action);
    setInstances((prev) =>
      prev.map((inst) => (inst.id === id ? updated : inst))
    );
    return updated;
  }

  // Remove instance from the local list after deletion
  async function remove(id: string): Promise<void> {
    await deleteInstance(id);
    setInstances((prev) => prev.filter((inst) => inst.id !== id));
  }

  return { instances, isLoading, error, create, updateStatus, remove };
}