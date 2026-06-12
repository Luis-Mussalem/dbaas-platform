// Registro de regiões: mapeia códigos (estilo AWS) para flag + cidade + país.
// Compartilhado por RegionTag (no card) e RegionMap (painel do dashboard).
// `lat`/`lon` são as coordenadas geográficas REAIS da cidade da região; o
// RegionMap as projeta num mapa-múndi para posicionar os marcadores.

export interface RegionInfo {
  code: string;
  flag: string;
  city: string;
  country: string; // sigla curta exibida (BR, US, IE…)
  lat: number;
  lon: number;
}

const REGIONS: Record<string, RegionInfo> = {
  "sa-east-1": { code: "sa-east-1", flag: "🇧🇷", city: "São Paulo", country: "BR", lat: -23.5, lon: -46.6 },
  "us-east-1": { code: "us-east-1", flag: "🇺🇸", city: "N. Virginia", country: "US", lat: 39.0, lon: -77.5 },
  "us-west-2": { code: "us-west-2", flag: "🇺🇸", city: "Oregon", country: "US", lat: 45.9, lon: -119.7 },
  "eu-west-1": { code: "eu-west-1", flag: "🇮🇪", city: "Ireland", country: "IE", lat: 53.3, lon: -6.3 },
  "eu-central-1": { code: "eu-central-1", flag: "🇩🇪", city: "Frankfurt", country: "DE", lat: 50.1, lon: 8.7 },
  "ap-southeast-1": { code: "ap-southeast-1", flag: "🇸🇬", city: "Singapore", country: "SG", lat: 1.35, lon: 103.8 },
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
      lat: 0,
      lon: 0,
    }
  );
}

// Projeção equiretangular (Plate Carrée): converte lat/lon em coordenadas de um
// mapa 2:1 com viewBox 360×180. É matemática linear pura — sem biblioteca de geo.
//   x  ∈ [0, 360]  →  lon -180 (oeste)  ..  +180 (leste)
//   y  ∈ [0, 180]  →  lat  +90 (norte)  ..   -90 (sul)
export function project(lat: number, lon: number): { x: number; y: number } {
  return { x: lon + 180, y: 90 - lat };
}
