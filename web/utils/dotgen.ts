// Dot density utilities using turf.
import bbox from "@turf/bbox";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { point } from "@turf/helpers";

type Position = [number, number];

// Generate `n` random points uniformly distributed inside a Polygon or MultiPolygon.
// Rejection sampling within the bounding box. For typical PUMA shapes this
// accepts on the first or second roll, so the safety cap rarely kicks in.
export function randomPointsInGeometry(
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon,
  n: number
): Position[] {
  if (n <= 0) return [];
  const feature: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> = {
    type: "Feature",
    geometry,
    properties: {},
  };
  const [minX, minY, maxX, maxY] = bbox(feature);
  const out: Position[] = [];
  let safety = n * 200;
  while (out.length < n && safety-- > 0) {
    const lng = minX + Math.random() * (maxX - minX);
    const lat = minY + Math.random() * (maxY - minY);
    if (booleanPointInPolygon(point([lng, lat]), feature)) {
      out.push([lng, lat]);
    }
  }
  return out;
}

// Build a FeatureCollection of dots for a given subculture.
// scores: { puma_code: { subculture_id: weighted_population } }
// dotsPerUnit: how many score-units each dot represents. Larger = fewer dots.
export function buildDotLayer(
  geojson: GeoJSON.FeatureCollection,
  scores: Record<string, Record<string, number>>,
  subcultureId: string,
  pumaCodeKeys: string[],
  dotsPerUnit: number
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const f of geojson.features) {
    const props = f.properties || {};
    let code: string | null = null;
    for (const k of pumaCodeKeys) {
      if (k in props && props[k]) {
        code = String(props[k]);
        break;
      }
    }
    if (!code) continue;
    const score = scores[code]?.[subcultureId] ?? 0;
    const n = Math.round(score / dotsPerUnit);
    if (n <= 0) continue;
    const geom = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon;
    if (geom.type !== "Polygon" && geom.type !== "MultiPolygon") continue;
    for (const [lng, lat] of randomPointsInGeometry(geom, n)) {
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [lng, lat] },
        properties: { puma: code, score },
      });
    }
  }
  return { type: "FeatureCollection", features };
}
