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

  // Abort guard: se companyId mudar antes do fetch terminar, descartamos o
  // resultado stale (mesmo padrão do use-audit.ts).
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    // Reset síncrono para "carregando" antes do refetch (troca de companyId /
    // reload). É intencional e abort-guarded; set-state-in-effect é conservadora
    // demais para este caso legítimo de data-fetching.
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
    // `t` só muda ao trocar de idioma (é memoizado pelo next-intl); refetch nesse
    // caso é aceitável e mantém a mensagem de erro no idioma corrente.
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
