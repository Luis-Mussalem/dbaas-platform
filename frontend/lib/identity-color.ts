// Cor de IDENTIDADE por instância — determinística a partir do id (hash estável).
// Dá variação visual aos avatares dos cards sem significado semântico.
//
// Regras seguidas (guia de dataviz):
//  - Paleta categórica FIXA, atribuída pela entidade (id), nunca ciclada por posição
//    na lista — a cor segue a instância, não seu ranking. Filtrar a lista não repinta.
//  - NÃO reutiliza os tons de status (ok/warn/danger/info): aqui a cor é identidade,
//    não estado.
//  - As iniciais no avatar são o identificador primário; a cor é reforço secundário,
//    então não precisa ser CVD-discriminável entre vizinhos.

const PALETTE: [string, string][] = [
  ["#6366f1", "#8b5cf6"], // indigo → violet
  ["#0ea5e9", "#06b6d4"], // sky → cyan
  ["#14b8a6", "#10b981"], // teal → emerald
  ["#f59e0b", "#f97316"], // amber → orange
  ["#f43f5e", "#ec4899"], // rose → pink
  ["#3b82f6", "#6366f1"], // blue → indigo
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

// Gradiente estável para o avatar da instância (mesmo id → mesma cor sempre).
export function instanceGradient(id: string): string {
  const [from, to] = PALETTE[hashString(id) % PALETTE.length];
  return `linear-gradient(135deg, ${from}, ${to})`;
}

// Até 2 iniciais a partir do nome (ex.: "checkout-prod" → "CP", "analytics" → "AN").
export function instanceInitials(name: string): string {
  const parts = name.replace(/[^a-zA-Z0-9]+/g, " ").trim().split(" ").filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : (name.trim().slice(0, 2) || "?");
  return letters.toUpperCase();
}
