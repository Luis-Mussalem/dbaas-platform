// Registro de regiões: mapeia códigos (estilo AWS) para flag + cidade + país.
// Compartilhado por RegionTag (no card) e RegionMap (painel do dashboard).
// `pos` são coordenadas aproximadas (0–100) num mapa-múndi equiretangular,
// usadas apenas para posicionar os pontos do mapa ilustrativo.

export interface RegionInfo {
  code: string;
  flag: string;
  city: string;
  country: string; // sigla curta exibida (BR, US, IE…)
  pos: { x: number; y: number };
}

const REGIONS: Record<string, RegionInfo> = {
  "sa-east-1": { code: "sa-east-1", flag: "🇧🇷", city: "São Paulo", country: "BR", pos: { x: 35, y: 72 } },
  "us-east-1": { code: "us-east-1", flag: "🇺🇸", city: "N. Virginia", country: "US", pos: { x: 24, y: 40 } },
  "us-west-2": { code: "us-west-2", flag: "🇺🇸", city: "Oregon", country: "US", pos: { x: 13, y: 38 } },
  "eu-west-1": { code: "eu-west-1", flag: "🇮🇪", city: "Ireland", country: "IE", pos: { x: 47, y: 32 } },
  "eu-central-1": { code: "eu-central-1", flag: "🇩🇪", city: "Frankfurt", country: "DE", pos: { x: 51, y: 34 } },
  "ap-southeast-1": { code: "ap-southeast-1", flag: "🇸🇬", city: "Singapore", country: "SG", pos: { x: 76, y: 60 } },
};

// Busca robusta: código desconhecido vira um item neutro (sem flag, sigla "—"),
// para a UI nunca quebrar com uma região que ainda não está no registro.
export function regionInfo(code: string | null): RegionInfo | null {
  if (!code) return null;
  return (
    REGIONS[code] ?? {
      code,
      flag: "🌐",
      city: code,
      country: code.slice(0, 2).toUpperCase(),
      pos: { x: 50, y: 50 },
    }
  );
}
