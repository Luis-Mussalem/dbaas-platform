"use client";

import { useEffect, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { listCompanies } from "@/lib/api";
import type { Company } from "@/lib/types";

// Chave usada para lembrar qual empresa o superuser deixou selecionada.
// (Por enquanto a seleção é só de exibição — quando os recursos passarem a ser
// escopados por empresa, é este id que vai filtrar instâncias, backups, etc.)
const ACTIVE_KEY = "active_company_id";

// O Workspace muda conforme o PAPEL do usuário (espelha o get_current_superuser
// do backend, que é quem libera a lista de empresas):
//   • superuser  → switcher: dropdown com todas as empresas, troca a ativa.
//   • comum      → rótulo fixo com a empresa dele (user.company), sem troca.
export function WorkspaceSwitcher() {
  const { user } = useAuth();

  if (!user) return null;

  return user.is_superuser ? (
    <SuperuserSwitcher />
  ) : (
    <FixedWorkspace name={user.company?.name ?? "Sem empresa"} />
  );
}

// ── Usuário comum: apenas exibe a empresa dele, sem interação ──
function FixedWorkspace({ name }: { name: string }) {
  return (
    <div className="mb-3.5 flex items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-2 text-left">
      <div className="h-5.5 w-5.5 shrink-0 rounded-md bg-linear-to-br from-primary to-info" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium">{name}</div>
        <div className="text-[11px] text-fg-3">Empresa</div>
      </div>
    </div>
  );
}

// ── Superuser: dropdown de troca de empresa ──
function SuperuserSwitcher() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  // Busca as empresas (rota restrita a superuser). Padrão das outras hooks:
  // fetch inline no effect, com guard `active` para descartar se desmontar.
  useEffect(() => {
    let active = true;
    listCompanies()
      .then((data) => {
        if (!active) return;
        setCompanies(data);
        // Restaura a seleção salva; se inválida/ausente, cai na primeira empresa.
        const saved = localStorage.getItem(ACTIVE_KEY);
        const valid = data.find((c) => c.id === saved);
        setActiveId(valid?.id ?? data[0]?.id ?? null);
      })
      .catch(() => {
        if (active) setCompanies([]);
      });
    return () => {
      active = false;
    };
  }, []);

  function select(id: string) {
    setActiveId(id);
    localStorage.setItem(ACTIVE_KEY, id);
    setOpen(false);
  }

  const activeName =
    companies.find((c) => c.id === activeId)?.name ??
    (companies.length === 0 ? "Sem empresas" : "Selecionar empresa");

  return (
    <div className="relative mb-3.5">
      <button
        onClick={() => companies.length > 0 && setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-2 text-left transition-colors hover:bg-surface-2"
      >
        <div className="h-5.5 w-5.5 shrink-0 rounded-md bg-linear-to-br from-primary to-info" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">{activeName}</div>
          <div className="text-[11px] text-fg-3">Workspace · admin</div>
        </div>
        <ChevronDown size={14} className="shrink-0 text-fg-3" />
      </button>

      {open && (
        <>
          {/* Camada invisível: um clique fora fecha o dropdown. */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <ul className="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-auto rounded-md border border-border bg-surface py-1 shadow-lg">
            {companies.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => select(c.id)}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground"
                >
                  <span className="flex-1 truncate">{c.name}</span>
                  {c.id === activeId && <Check size={13} className="shrink-0 text-brand" />}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
