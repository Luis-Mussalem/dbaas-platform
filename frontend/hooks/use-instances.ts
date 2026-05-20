import { useEffect, useState } from "react";
import { createInstance, listInstances } from "@/lib/api";
import type { Instance, InstanceCreate } from "@/lib/types";

interface UseInstancesResult {
  instances: Instance[];
  isLoading: boolean;
  error: string | null;
  create: (data: InstanceCreate) => Promise<void>;
}

export function useInstances(): UseInstancesResult {
  const [instances, setInstances] = useState<Instance[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listInstances()
      .then(setInstances)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setIsLoading(false));
  }, []);

  async function create(data: InstanceCreate): Promise<void> {
    const instance = await createInstance(data);
    setInstances((prev) => [...prev, instance]);
  }

  return { instances, isLoading, error, create };
}
