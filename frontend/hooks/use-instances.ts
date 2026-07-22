import { useCallback } from "react";
import { useTranslations } from "next-intl";
import {
  createInstance,
  deleteInstance,
  listInstances,
  updateInstanceStatus,
} from "@/lib/api";
import { useResource } from "@/hooks/use-resource";
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

// `pollMs` (DASHBOARD_POLL_MS) mantém a lista fresca; sem ele, a busca é só no mount.
export function useInstances(pollMs?: number, version?: number): UseInstancesResult {
  const t = useTranslations("Instances");
  const fetcher = useCallback(() => listInstances(), []);
  const { data, isLoading, error, setData } = useResource(
    fetcher,
    t("loadFailed"),
    pollMs,
    version
  );
  const instances = data ?? [];

  // Add new instance to the local list after creation
  async function create(payload: InstanceCreate): Promise<void> {
    const instance = await createInstance(payload);
    setData((prev) => [...(prev ?? []), instance]);
  }

  // Update status of one instance in the local list
  // Returns the updated instance so the detail page can set its own state
  async function updateStatus(id: string, action: "start" | "stop"): Promise<Instance> {
    const updated = await updateInstanceStatus(id, action);
    setData((prev) =>
      (prev ?? []).map((inst) => (inst.id === id ? updated : inst))
    );
    return updated;
  }

  // Remove instance from the local list after deletion
  async function remove(id: string): Promise<void> {
    await deleteInstance(id);
    setData((prev) => (prev ?? []).filter((inst) => inst.id !== id));
  }

  return { instances, isLoading, error, create, updateStatus, remove };
}
