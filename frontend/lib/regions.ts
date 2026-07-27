// Region registry: maps codes (AWS-style) to flag + city + country.
// Shared by RegionTag (in the card), RegionMap (dashboard), and the creation wizard.
// `lat`/`lon` are the region's city's REAL geographic coordinates; the
// RegionMap projects them onto a world map to position the markers.
//
// Deliberately left out of i18n: cities and region codes are infrastructure
// proper nouns — AWS doesn't call sa-east-1 "South America East" in Portuguese.

export interface RegionInfo {
  code: string;
  flag: string;
  city: string;
  country: string; // short displayed code (BR, US, IE…)
  lat: number;
  lon: number;
}

const REGIONS: Record<string, RegionInfo> = {
  "sa-east-1": { code: "sa-east-1", flag: "🇧🇷", city: "São Paulo", country: "BR", lat: -23.5, lon: -46.6 },
  "us-east-1": { code: "us-east-1", flag: "🇺🇸", city: "N. Virginia", country: "US", lat: 39.0, lon: -77.5 },
  "eu-west-1": { code: "eu-west-1", flag: "🇮🇪", city: "Ireland", country: "IE", lat: 53.3, lon: -6.3 },
  "eu-central-1": { code: "eu-central-1", flag: "🇩🇪", city: "Frankfurt", country: "DE", lat: 50.1, lon: 8.7 },
  "ap-southeast-1": { code: "ap-southeast-1", flag: "🇸🇬", city: "Singapore", country: "SG", lat: 1.35, lon: 103.8 },
};

// All known regions, in declaration order — used by the creation wizard,
// which used to keep its own (and outdated) copy of this list.
export function listRegions(): RegionInfo[] {
  return Object.values(REGIONS);
}

// Robust lookup: an unknown code becomes a neutral item (no flag, "—" code),
// so the UI never breaks on a region that isn't in the registry yet.
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

// Equirectangular projection (Plate Carrée): converts lat/lon into coordinates of a
// 2:1 map with a 360×180 viewBox. It's pure linear math — no geo library.
//   x  ∈ [0, 360]  →  lon -180 (west)  ..  +180 (east)
//   y  ∈ [0, 180]  →  lat  +90 (north)  ..   -90 (south)
export function project(lat: number, lon: number): { x: number; y: number } {
  return { x: lon + 180, y: 90 - lat };
}
