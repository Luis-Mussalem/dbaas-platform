import { Check, Minus, ShieldCheck } from "lucide-react";

// Matriz de capacidades por papel — estática, refletindo as regras REAIS de
// autorização do backend (core/scoping.py: is_company_admin / assert_can_manage_target;
// services/user.py: create_user_admin / update_user_admin; dependencies.py).
// Não há permissão fina por recurso: os eixos reais são is_superuser × role.
const ROLES = ["Member", "Company Admin", "Superuser"] as const;

const CAPABILITIES: { label: string; allowed: [boolean, boolean, boolean] }[] = [
  { label: "Ver o próprio perfil", allowed: [true, true, true] },
  { label: "Ver outros usuários", allowed: [false, false, true] },
  { label: "Listar usuários da empresa", allowed: [false, true, true] },
  { label: "Criar usuários", allowed: [false, true, true] },
  { label: "Editar papel / status", allowed: [false, true, true] },
  { label: "Alternar flag de superuser", allowed: [false, false, true] },
  { label: "Ver registro de auditoria", allowed: [false, true, true] },
  { label: "Visibilidade entre empresas", allowed: [false, false, true] },
];

export function CapabilityLegend() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <ShieldCheck size={16} className="text-fg-2" />
        <h2 className="text-sm font-semibold">Matriz de permissões</h2>
        <span className="text-xs text-fg-3">o que cada papel pode fazer</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11.5px] uppercase tracking-wide text-fg-3">
              <th className="px-4 py-2 font-medium">Capacidade</th>
              {ROLES.map((r) => (
                <th key={r} className="px-4 py-2 text-center font-medium">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CAPABILITIES.map((cap) => (
              <tr key={cap.label} className="border-t border-border">
                <td className="px-4 py-2 text-fg-2">{cap.label}</td>
                {cap.allowed.map((ok, i) => (
                  <td key={i} className="px-4 py-2 text-center">
                    {ok ? (
                      <Check size={15} className="mx-auto text-ok" />
                    ) : (
                      <Minus size={15} className="mx-auto text-fg-3" />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border px-4 py-2.5 text-[11.5px] text-fg-3">
        Company admins agem apenas dentro da própria empresa e nunca sobre superusers.
      </p>
    </div>
  );
}
