"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Scores } from "@/app/page";
import { buildDotLayer } from "@/utils/dotgen";

interface Props {
  geojson: GeoJSON.FeatureCollection;
  scores: Scores;
  selectedIds: string[];
}

// Geometry code property keys, in order of preference. First three are tract
// GEOIDs from TIGER tract files; the rest are PUMA fallbacks if you revert
// the data sources in app/page.tsx to PUMA-level.
const PUMA_CODE_KEYS = ["GEOID", "GEOID20", "GEOIDFQ", "PUMACE20", "PUMA20", "PUMACE10", "PUMACE", "PUMA"];

// One dot per N units of weighted score, applied uniformly across subcultures.
// Smaller subcultures genuinely show as fewer dots — that's the honest picture.
const DOTS_PER_UNIT = 150;

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

const COLORS: Record<string, string> = {
  queer_leftist: "#2563eb",
  bilingual_baddie: "#f97316",
  crumbl_cookie_couple: "#ec4899",
  wino: "#722f37",
  hill_people: "#355E3B",
  stupid_guy: "#8b6f47",
};

const FALLBACK_COLOR = "#3567d8";

// Build a "match" expression mapping subculture id to color, for use as
// circle-color in a single layer that holds dots from all selected subcultures.
function colorMatchExpression(): maplibregl.ExpressionSpecification {
  const args: (string | string[])[] = ["match", ["get", "subculture"]];
  for (const [id, color] of Object.entries(COLORS)) {
    args.push(id, color);
  }
  args.push(FALLBACK_COLOR);
  return args as unknown as maplibregl.ExpressionSpecification;
}

export default function MapView({ geojson, scores, selectedIds }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const beforeIdRef = useRef<string | undefined>(undefined);

  // Generate dots for all selected subcultures, each tagged with its subculture id.
  // Shuffle the combined feature array (Fisher-Yates) so that paint order is random
  // across subcultures: no single subculture sits consistently on top.
  const dots = useMemo(() => {
    const all: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [],
    };
    for (const id of selectedIds) {
      const fc = buildDotLayer(geojson, scores, id, PUMA_CODE_KEYS, DOTS_PER_UNIT);
      for (const f of fc.features) {
        f.properties = { ...(f.properties ?? {}), subculture: id };
        all.features.push(f);
      }
    }
    for (let i = all.features.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [all.features[i], all.features[j]] = [all.features[j], all.features[i]];
    }
    return all;
  }, [geojson, scores, selectedIds]);

  // Initial map setup.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [-119.5, 37.5],
      zoom: 5.2,
      minZoom: 5,
      maxPitch: 60,
      // California-ish bounding box: SW to NE corners. Pan and zoom-out beyond
      // these are clamped, so the user can't drift off into Nevada or the Pacific.
      maxBounds: [
        [-125.5, 32.0],
        [-113.5, 42.5],
      ],
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({ compact: true, customAttribution: "OpenFreeMap" }),
      "bottom-right"
    );
    mapRef.current = map;

    map.on("load", () => {
      // Identify the first symbol (label) layer in the basemap so we can
      // insert our dot/PUMA layers below it. This makes city and place names
      // render on top of the dots rather than being obscured.
      const layers = map.getStyle().layers ?? [];
      const firstSymbol = layers.find((l) => l.type === "symbol");
      beforeIdRef.current = firstSymbol?.id;

      const beforeId = beforeIdRef.current;

      // Dots layer: single source/layer, color driven by `subculture` property.
      map.addSource("dots", { type: "geojson", data: dots });
      map.addLayer(
        {
          id: "dots-circle",
          type: "circle",
          source: "dots",
          paint: {
            "circle-radius": [
              "interpolate",
              ["exponential", 1.6],
              ["zoom"],
              4, 0.6,
              6, 1.4,
              8, 2.8,
              10, 4.5,
              13, 7,
              16, 10,
            ],
            "circle-color": colorMatchExpression(),
            "circle-opacity": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4, 0.25,
              6, 0.4,
              8, 0.6,
              11, 0.7,
            ],
            "circle-blur": 0.2,
            "circle-pitch-alignment": "map",
          },
        },
        beforeId
      );

    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push generated dots into the dots source whenever they change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const src = map.getSource("dots") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(dots);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [dots]);



  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 12,
          fontSize: 11,
          color: "#6a7283",
          fontFamily: "ui-monospace, monospace",
          background: "rgba(255,255,255,0.85)",
          padding: "4px 8px",
          borderRadius: 4,
        }}
      >
        {dots.features.length.toLocaleString()} dots ·{" "}
        {selectedIds.length} subculture{selectedIds.length === 1 ? "" : "s"} · 1 dot ≈{" "}
        {DOTS_PER_UNIT.toLocaleString()} units
      </div>
    </div>
  );
}
