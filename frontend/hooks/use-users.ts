import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  createUserAdmin,
  deactivateUser,
  listUsers,
  updateUserAdmin,
} from "@/lib/api";
import type { User, UserAdminCreate, UserAdminUpdate } from "@/lib/types";

interface UseUsersResult {
  users: User[];
  isLoading: boolean;
  error: string | null;
  create: (data: UserAdminCreate) => Promise<void>;
  update: (userId: string, data: UserAdminUpdate) => Promise<void>;
  deactivate: (userId: string) => Promise<void>;
  reload: () => void;
}

export function useUsers(companyId?: string): UseUsersResult {
  const t = useTranslations("Common");
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Abort guard: if companyId changes before the fetch finishes, we discard the
  // stale result (same pattern as use-audit.ts).
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    // Synchronous reset to "loading" before the refetch (companyId change /
    // reload). It's intentional and abort-guarded; set-state-in-effect is too
    // conservative for this legitimate data-fetching case.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsLoading(true);
    setError(null);

    listUsers(companyId)
      .then((data) => {
        if (activeRef.current) setUsers(data);
      })
      .catch((err) => {
        if (activeRef.current)
          setError(err instanceof Error ? err.message : t("loadFailed"));
      })
      .finally(() => {
        if (activeRef.current) setIsLoading(false);
      });

    return () => {
      activeRef.current = false;
    };
    // `t` only changes when the language changes (it's memoized by next-intl); refetching in
    // that case is acceptable and keeps the error message in the current language.
  }, [companyId, tick, t]);

  async function create(data: UserAdminCreate): Promise<void> {
    const created = await createUserAdmin(data);
    setUsers((prev) => [...prev, created].sort((a, b) => a.email.localeCompare(b.email)));
  }

  async function update(userId: string, data: UserAdminUpdate): Promise<void> {
    const updated = await updateUserAdmin(userId, data);
    setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
  }

  async function deactivate(userId: string): Promise<void> {
    const updated = await deactivateUser(userId);
    setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
  }

  function reload(): void {
    setTick((t) => t + 1);
  }

  return { users, isLoading, error, create, update, deactivate, reload };
}
