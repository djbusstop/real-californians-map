"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Scores } from "@/app/page";
import { buildDotLayer } from "@/utils/dotgen";
import { COLORS, FALLBACK_COLOR } from "@/lib/colors";

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
const DOTS_PER_UNIT = 20;

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";


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
  // Flips true once the basemap has loaded and the dots source/layer are
  // installed. The data-sync effect keys off this so it doesn't try to
  // setData on a source that does not exist yet, and so it doesn't depend
  // on isStyleLoaded() — which can flip false transiently during tile
  // fetches and silently drop data updates if we gated on it.
  const [mapReady, setMapReady] = useState(false);
  // Live zoom level, displayed in the bottom-left readout for tuning the
  // circle-radius interpolation curve in the dots-circle paint property.
  const [zoom, setZoom] = useState<number>(5.2);

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
      minZoom: 4,
      maxPitch: 60,
      // California-centered bounding box. ~6° horizontal padding (about half
      // California's lon width) gives breathing room east/west to see ocean
      // and Nevada; vertical padding is kept tight (~1°) since N/S drift
      // adds little context.
      maxBounds: [
        [-131.5, 31.0],
        [-107.5, 43.5],
      ],
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({ compact: true, customAttribution: "OpenFreeMap" }),
      "bottom-right"
    );
    mapRef.current = map;
    map.on("zoom", () => setZoom(map.getZoom()));

    map.on("load", () => {
      // Identify the first symbol (label) layer in the basemap so we can
      // insert our dot/PUMA layers below it. This makes city and place names
      // render on top of the dots rather than being obscured.
      const layers = map.getStyle().layers ?? [];
      const firstSymbol = layers.find((l) => l.type === "symbol");
      beforeIdRef.current = firstSymbol?.id;

      const beforeId = beforeIdRef.current;

      // Dots layer: single source/layer, color driven by `subculture` property.
      // Initialize the source empty; the data-sync effect populates it once
      // mapReady is true. This avoids closing over a stale `dots` value here.
      map.addSource("dots", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
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
              4, 0.7,
              6, 1,
              8, 1.3,
              10, 2.0,
              12, 3.2,
              15, 7.0,
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

      setMapReady(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push generated dots into the dots source whenever they change. We gate
  // on `mapReady` (set true inside the load handler above), so by the time
  // this runs the source is guaranteed to exist. Calling setData directly
  // is safe regardless of whether the basemap is mid-tile-load — we used
  // to gate on isStyleLoaded(), which flips false transiently and caused
  // updates to be queued onto a `load` event that never fired again,
  // dropping them silently. That was the cause of stuck dots after clear.
  useEffect(() => {
    if (!mapReady) return;
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource("dots") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(dots);
  }, [dots, mapReady]);




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
        {DOTS_PER_UNIT.toLocaleString()} people · zoom {zoom.toFixed(2)}
      </div>
    </div>
  );
}
