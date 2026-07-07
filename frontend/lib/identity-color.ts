// Cor de IDENTIDADE da instância — determinística, agrupada por EMPRESA.
//
// Regra: a MATIZ (família de cor) vem da empresa — o primeiro token do nome, ex.:
// "jupiter-clothing-prod" → "jupiter". Assim todas as instâncias da mesma empresa
// compartilham a mesma família (Jupiter=roxo, Saturn=azul, Neptune=laranja…), e o
// AMBIENTE escolhe o TOM dentro da família (produção mais forte, homologação mais
// clara) — "parecidas mas diferentes". A mesma cor alimenta o avatar e a linha do
// sparkline do card.
//
// Segue o guia de dataviz: paleta categórica fixa atribuída pela entidade (empresa),
// nunca ciclada por posição na lista; não reutiliza os tons de status (ok/warn/danger).

import type { Environment } from "@/lib/types";

// [forte, médio, claro] por família. A ORDEM é escolhida para as empresas demo
// caírem nas cores pedidas via o hash do token (jupiter→3, saturn→5, neptune→1).
const FAMILIES: [string, string, string][] = [
  ["#0f766e", "#14b8a6", "#5eead4"], // 0 teal
  ["#c2410c", "#f97316", "#fdba74"], // 1 laranja  ← neptune
  ["#be185d", "#ec4899", "#f9a8d4"], // 2 rosa
  ["#6d28d9", "#8b5cf6", "#c4b5fd"], // 3 roxo     ← jupiter
  ["#4338ca", "#6366f1", "#a5b4fc"], // 4 índigo
  ["#1d4ed8", "#3b82f6", "#93c5fd"], // 5 azul      ← saturn
  ["#15803d", "#22c55e", "#86efac"], // 6 verde
  ["#b45309", "#f59e0b", "#fcd34d"], // 7 âmbar
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

// Chave da empresa = primeiro token alfanumérico do nome.
// "jupiter-clothing-prod" → "jupiter"; "neptune-payments-staging" → "neptune".
function companyKey(name: string): string {
  const token = name.trim().toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)[0];
  return token || name.trim().toLowerCase();
}

function family(name: string): [string, string, string] {
  return FAMILIES[hashString(companyKey(name)) % FAMILIES.length];
}

// Ambiente → índice do tom: produção = forte (0), homologação/indef = médio (1),
// desenvolvimento = claro (2).
function shadeIndex(env: Environment | null): number {
  if (env === "production") return 0;
  if (env === "development") return 2;
  return 1;
}

// Gradiente do avatar (mesma família, tom pelo ambiente). Sempre termina no tom
// mais escuro para manter as iniciais brancas legíveis.
export function instanceGradient(name: string, env: Environment | null): string {
  const [deep, mid, light] = family(name);
  const [from, to] = shadeIndex(env) === 0 ? [mid, deep] : [light, mid];
  return `linear-gradient(135deg, ${from}, ${to})`;
}

// Cor sólida da linha do sparkline — mesma família/tom do avatar.
export function instanceLineColor(name: string, env: Environment | null): string {
  return family(name)[shadeIndex(env)];
}

// Até 2 iniciais a partir do nome (ex.: "checkout-prod" → "CP", "analytics" → "AN").
export function instanceInitials(name: string): string {
  const parts = name.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ").filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (name.trim().slice(0, 2) || "?");
  return letters.toUpperCase();
}
