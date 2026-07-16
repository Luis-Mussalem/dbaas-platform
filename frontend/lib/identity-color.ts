// Cor de IDENTIDADE da instância — determinística, agrupada por PAÍS da região.
//
// A MATIZ vem do país (cor da bandeira): Brasil = verde, EUA = azul, Irlanda =
// laranja, Alemanha = dourado, Singapura = vermelho. O AMBIENTE escolhe o TOM: a
// produção usa a cor cheia da bandeira; homologação e desenvolvimento usam tons
// mais claros (misturados em direção à superfície do tema). Instâncias do mesmo
// país compartilham a família e o ambiente as diferencia.
//
// Por que por país, e não por empresa (hash do nome): ao criar uma empresa nova o
// hash antigo podia colidir/confundir cores. Ancorar no país torna a cor
// PREVISÍVEL — segue a região escolhida, não o nome. A mesma cor alimenta o avatar,
// a linha do sparkline (card) e os marcadores do mapa de regiões.
//
// Cores mid-tone escolhidas para funcionar nos temas claro E escuro sem trocar de
// matiz. Segue o guia de dataviz: paleta categórica fixa por entidade (país), com
// reforço secundário pela bandeira + sigla do país (nunca só a cor).

import type { Environment } from "@/lib/types";
import { regionInfo } from "@/lib/regions";

// País (sigla) → { fill: cor base = tom preciso da bandeira (produção);
//                  ink: cor do texto sobre essa cor }.
const COUNTRY_COLORS: Record<string, { fill: string; ink: string }> = {
  BR: { fill: "#007a33", ink: "#ffffff" }, // verde bandeira fechado — distinto do
                                           // verde-tema esmeralda (#10b981), ΔE ~19
  US: { fill: "#2563eb", ink: "#ffffff" }, // azul visível
  IE: { fill: "#ff8200", ink: "#ffffff" }, // laranja (Pantone 151)
  DE: { fill: "#f5c518", ink: "#1a1a1a" }, // amarelo-dourado — puxado para o amarelo
                                           // p/ separar do laranja da Irlanda; texto escuro
  SG: { fill: "#ee2536", ink: "#ffffff" }, // vermelho (Pantone 032)
};

// País desconhecido → cor da marca (mesmo espírito do fallback de regionInfo, que
// nunca quebra a UI). Como é um token, não entra no color-mix dos tons.
const FALLBACK = { fill: "var(--brand)", ink: "var(--brand-fg)" };

function colorFor(region: string | null): { fill: string; ink: string } {
  const info = regionInfo(region);
  if (!info) return FALLBACK;
  return COUNTRY_COLORS[info.country] ?? FALLBACK;
}

// Ambiente → tom: produção = cor cheia; homologação/indef = leve clareamento;
// desenvolvimento = mais claro. A mistura é feita com CSS color-mix contra a
// superfície do tema vigente, então clareia no claro e escurece no escuro —
// legível nos dois sem trocar de matiz. Tokens de marca não são misturados.
function envTone(fill: string, env: Environment | null): string {
  if (fill.startsWith("var(") || env === "production") return fill;
  const surfaceMix = env === "development" ? 34 : 18; // % de superfície
  return `color-mix(in oklch, ${fill} ${100 - surfaceMix}%, var(--surface))`;
}

// Gradiente do avatar: do tom do ambiente para uma versão levemente mais escura
// (profundidade). O texto usa a `ink` do país (branco, ou escuro sobre o dourado).
export function instanceGradient(region: string | null, env: Environment | null): string {
  const tone = envTone(colorFor(region).fill, env);
  if (tone.startsWith("var(")) return `linear-gradient(135deg, ${tone}, ${tone})`;
  return `linear-gradient(135deg, ${tone}, color-mix(in oklch, ${tone}, black 14%))`;
}

// Cor sólida da linha do sparkline — mesmo tom do avatar.
export function instanceLineColor(region: string | null, env: Environment | null): string {
  return envTone(colorFor(region).fill, env);
}

// Cor do texto das iniciais sobre o avatar (branco na maioria; escuro no dourado).
export function instanceInk(region: string | null): string {
  return colorFor(region).ink;
}

// Cor sólida do país (tom de produção) — usada pelos marcadores do mapa de regiões.
export function countryColor(region: string | null): string {
  return colorFor(region).fill;
}

// Até 2 iniciais a partir do nome (ex.: "checkout-prod" → "CP", "analytics" → "AN").
// O nome continua definindo as INICIAIS; só a COR passou a vir do país.
export function instanceInitials(name: string): string {
  const parts = name.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ").filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (name.trim().slice(0, 2) || "?");
  return letters.toUpperCase();
}
