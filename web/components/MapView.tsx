"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Cohort } from "@/lib/types";
import { buildDotLayer } from "@/utils/dotgen";
import { AUTHORED_COHORT_COLOR } from "@/lib/constants";
import CustomCohorts from "./CustomCohorts";

interface Props {
  cohorts: Cohort[];
}

// Internal type alias for the merged scores object: per-tract,
// per-cohort weighted member count. Built by flattening the cohorts
// prop; not exported because no other component needs it.
type Scores = Record<string, Record<string, number>>;

// Geometry code property keys, in order of preference. First three are
// tract GEOIDs from TIGER tract files; the rest are PUMA fallbacks if
// you revert the data sources to PUMA-level.
const PUMA_CODE_KEYS = [
  "GEOID",
  "GEOID20",
  "GEOIDFQ",
  "PUMACE20",
  "PUMA20",
  "PUMACE10",
  "PUMACE",
  "PUMA",
];

// One dot per N units of weighted score, applied uniformly across cohorts.
// Smaller cohorts genuinely show as fewer dots — the honest picture.
const DOTS_PER_UNIT = 10;

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

// Default color for any cohort id the cohorts prop does not cover (e.g.,
// stale dots from a prior render with a different cohort set). Should
// rarely trigger in practice.
const FALLBACK_COLOR = "#7eaaff";

// Base zoom→radius stops for the dot circle layer. The actual paint
// expression multiplies these by a user-controlled scale factor (the
// slider in the bottom-left) so the user can scale dots up or down
// relative to the natural zoom curve without re-rendering the dot data.
const BASE_RADIUS_STOPS: [number, number][] = [
  [4, 0.7],
  [6, 1.0],
  [8, 1.3],
  [10, 2.0],
  [12, 3.2],
  [15, 7.0],
];

function buildRadiusExpression(
  scale: number,
): maplibregl.ExpressionSpecification {
  const interp: (string | number | string[])[] = [
    "interpolate",
    // @ts-ignore
    ["exponential", 1.6],
    ["zoom"],
  ];
  for (const [z, r] of BASE_RADIUS_STOPS) {
    interp.push(z, r * scale);
  }
  return interp as unknown as maplibregl.ExpressionSpecification;
}

// Build a "match" expression mapping cohort id to color from the
// cohorts prop. Replaces the old static COLORS dict — colors now live
// on each cohort object, so a new user-created cohort can declare its
// own color and have it picked up automatically.
function buildColorMatchExpression(
  cohorts: Cohort[],
): maplibregl.ExpressionSpecification {
  const args: (string | string[])[] = ["match", ["get", "subculture"]];
  for (const c of cohorts) {
    args.push(c.id, c.color);
  }
  args.push(FALLBACK_COLOR);
  return args as unknown as maplibregl.ExpressionSpecification;
}

export default function MapView({ cohorts }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const beforeIdRef = useRef<string | undefined>(undefined);

  // Per-cohort selection toggled by clicking legend rows. Default
  // state: every library cohort selected (= visible).
  // Not persisted across reloads. Stale ids are harmless: they don't
  // match any current cohort.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(cohorts.map((c) => c.id)),
  );

  const toggleCohort = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Cohorts that actually paint on the map: those currently selected.
  // All downstream map computations (mergedScores, dots, color
  // expression, info bar count) use this filtered set; only the
  // legend itself reads from allCohorts.
  const visibleCohorts = useMemo<Cohort[]>(
    () => cohorts.filter((c) => selectedIds.has(c.id)),
    [cohorts, selectedIds],
  );

  // Flips true once the basemap has loaded and the dots source/layer
  // are installed. The data-sync effect keys off this so it doesn't try
  // to setData on a source that does not exist yet, and so it doesn't
  // depend on isStyleLoaded() — which can flip false transiently during
  // tile fetches and silently drop data updates if we gated on it.
  const [mapReady, setMapReady] = useState(false);
  // User-controlled multiplier on the base radius curve. 1.0 = the curve
  // defined by BASE_RADIUS_STOPS; anything else scales every stop
  // uniformly.
  const [dotScale, setDotScale] = useState<number>(1.0);
  // Tracts geometry. Fetched client-side because the file is large
  // (~85MB) and the browser caches it well across visits. Inlining
  // server-side would balloon the HTML payload on every fresh request.
  const [geojson, setGeojson] = useState<GeoJSON.FeatureCollection | null>(
    null,
  );
  const [geojsonError, setGeojsonError] = useState<string | null>(null);

  // Merge per-cohort tract_scores into one Scores object that
  // buildDotLayer expects. Each cohort's tract_scores is already in
  // {tract_geoid: {id: score}} shape, so merging is a shallow
  // tract-by-tract union.
  const mergedScores = useMemo<Scores>(() => {
    const out: Scores = {};
    for (const c of visibleCohorts) {
      for (const [tract, scoreObj] of Object.entries(c.tract_scores)) {
        if (!out[tract]) out[tract] = {};
        Object.assign(out[tract], scoreObj);
      }
    }
    return out;
  }, [visibleCohorts]);

  // Fetch tracts geometry once on mount.
  useEffect(() => {
    let cancelled = false;
    fetch("/data/tracts_ca.geojson")
      .then((r) => {
        if (!r.ok) throw new Error(`tracts_ca.geojson: ${r.status}`);
        return r.json();
      })
      .then((g) => {
        if (!cancelled) setGeojson(g);
      })
      .catch((err) => {
        if (!cancelled) setGeojsonError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Generate dots for every cohort, each tagged with its id. Shuffle
  // the combined feature array (Fisher-Yates) so paint order is random
  // across cohorts: no single cohort sits consistently on top.
  const dots = useMemo<GeoJSON.FeatureCollection>(() => {
    const all: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [],
    };
    if (!geojson) return all;
    for (const c of visibleCohorts) {
      const fc = buildDotLayer(
        geojson,
        mergedScores,
        c.id,
        PUMA_CODE_KEYS,
        DOTS_PER_UNIT,
      );
      for (const f of fc.features) {
        f.properties = { ...(f.properties ?? {}), subculture: c.id };
        all.features.push(f);
      }
    }
    for (let i = all.features.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [all.features[i], all.features[j]] = [all.features[j], all.features[i]];
    }
    return all;
  }, [geojson, mergedScores, visibleCohorts]);

  // Initial map setup. Runs once on mount.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [-119.5, 37.5],
      zoom: 5.2,
      minZoom: 4,
      maxPitch: 60,
      // California-centered bounding box. ~6° horizontal padding (about
      // half California's lon width) gives breathing room east/west to
      // see ocean and Nevada; vertical padding is kept tight (~1°)
      // since N/S drift adds little context.
      maxBounds: [
        [-131.5, 31.0],
        [-107.5, 43.5],
      ],
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "OpenFreeMap",
      }),
      "bottom-right",
    );
    mapRef.current = map;

    map.on("load", () => {
      // Identify the first symbol (label) layer in the basemap so we
      // can insert our dot layer below it. This makes city and place
      // names render on top of the dots rather than being obscured.
      const layers = map.getStyle().layers ?? [];
      const firstSymbol = layers.find((l) => l.type === "symbol");
      beforeIdRef.current = firstSymbol?.id;

      // Dots layer: single source/layer, color driven by `subculture`
      // property. Initialize the source empty; the data-sync effect
      // populates it once mapReady is true. This avoids closing over a
      // stale `dots` value here.
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
            "circle-radius": buildRadiusExpression(1.0),
            // The initial color expression is built from the cohorts
            // prop at first render; the cohorts-change effect below
            // updates it if the prop ever changes.
            "circle-color": buildColorMatchExpression(visibleCohorts),
            "circle-opacity": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              0.25,
              6,
              0.4,
              8,
              0.6,
              11,
              0.7,
            ],
            "circle-blur": 0.2,
            "circle-pitch-alignment": "map",
          },
        },
        beforeIdRef.current,
      );

      setMapReady(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push generated dots into the dots source whenever they change.
  // Gated on mapReady so the source exists before setData runs.
  useEffect(() => {
    if (!mapReady) return;
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource("dots") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(dots);
  }, [dots, mapReady]);

  // Push the user's dot-scale multiplier into the dots-circle paint
  // property whenever the slider moves. Rebuilds the radius
  // interpolation expression with each base stop multiplied by
  // `dotScale` and applies it without touching the dot source data.
  useEffect(() => {
    if (!mapReady) return;
    const map = mapRef.current;
    if (!map) return;
    map.setPaintProperty(
      "dots-circle",
      "circle-radius",
      buildRadiusExpression(dotScale),
    );
  }, [dotScale, mapReady]);

  // Rebuild the color match expression if the cohort set changes
  // (library updated or chat-authored cohort arrived / cleared). The
  // map is already initialized so we just setPaintProperty rather
  // than rebuilding the layer.
  useEffect(() => {
    if (!mapReady) return;
    const map = mapRef.current;
    if (!map) return;
    map.setPaintProperty(
      "dots-circle",
      "circle-color",
      buildColorMatchExpression(visibleCohorts),
    );
  }, [visibleCohorts, mapReady]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      {/* Bottom-left card */}
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
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 8,
          maxWidth: "calc(100vw - 24px)",
          boxSizing: "border-box",
        }}
      >
        <span className="map-info-text">
          {dots.features.length.toLocaleString()} dots · {visibleCohorts.length}{" "}
          cohort
          {visibleCohorts.length === 1 ? "" : "s"} · 1 dot ≈{" "}
          {DOTS_PER_UNIT.toLocaleString()} people
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="dot-size-separator">· </span>
          <span>dot size</span>
          <input
            type="range"
            min={0.8}
            max={2.5}
            step={0.1}
            value={dotScale}
            onChange={(e) => setDotScale(parseFloat(e.target.value))}
            className="dot-size-slider"
            style={{ width: 100, cursor: "pointer" }}
            aria-label="Dot size scale"
          />
          <span style={{ minWidth: 28, textAlign: "right" }}>
            {dotScale.toFixed(1)}×
          </span>
        </span>
      </div>
      {/* Loading */}
      {!geojson && !geojsonError && !mapRef.current?.getSource("dots") && (
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 60,
            padding: "6px 12px",
            background: "rgba(255,255,255,0.95)",
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            fontSize: 11,
            color: "#6b7280",
            pointerEvents: "none",
          }}
        >
          Loading...
        </div>
      )}
      {/* Error */}
      {geojsonError && (
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 60,
            padding: "6px 12px",
            background: "rgba(254,242,242,0.95)",
            border: "1px solid #fecaca",
            borderRadius: 4,
            fontSize: 11,
            color: "#991b1b",
          }}
        >
          Map failed to load: {geojsonError}
        </div>
      )}
      {/* Top-left stack: legend*/}
      <div
        className="cohort-legend"
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div
          style={{
            // Match the bottom-left info bar and cohort builder button:
            // monospace 11px, light-gray translucent background, thin
            // border, no shadow.
            background: "rgba(255,255,255,0.85)",
            border: "1px solid rgba(0,0,0,0.08)",
            borderRadius: 4,
            padding: "4px 8px",
            fontSize: 12,
            color: "#1a1f2e",
            fontFamily: "ui-monospace, monospace",
            minWidth: 140,
            width: "fit-content",
          }}
        >
          <div
            style={{
              fontSize: 16,
              fontWeight: 500,
              lineHeight: 1.2,
              whiteSpace: "nowrap",
              padding: "2px 0 4px",
              borderBottom: "1px solid rgba(0,0,0,0.06)",
              marginBottom: 6,
            }}
          >
            California Culture Map
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              gap: 16,
              color: "#6a7283",
              marginBottom: 4,
            }}
          >
            <span style={{ fontSize: 14 }}>Legend</span>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              disabled={selectedIds.size === 0}
              title="hide every layer"
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                cursor: selectedIds.size === 0 ? "default" : "pointer",
                fontSize: 12,
                fontFamily: "ui-monospace, monospace",
                color: selectedIds.size === 0 ? "#d1d5db" : "#6a7283",
                textDecoration: selectedIds.size === 0 ? "none" : "underline",
                flexShrink: 0,
              }}
            >
              clear
            </button>
          </div>
          {cohorts.map((c) => {
            const selected = selectedIds.has(c.id);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => toggleCohort(c.id)}
                title={selected ? "hide cohort" : "show cohort"}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "2px 0",
                  lineHeight: 1.3,
                  background: "transparent",
                  border: "none",
                  textAlign: "left",
                  cursor: "pointer",
                  font: "inherit",
                  color: selected ? "#1a1f2e" : "#9ca3af",
                  width: "100%",
                }}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 5,
                    background: selected ? c.color : "transparent",
                    border: selected ? "none" : `2px solid ${c.color}`,
                    flexShrink: 0,
                    boxSizing: "border-box",
                    opacity: selected ? 1 : 0.55,
                  }}
                />
                <span style={{ opacity: selected ? 1 : 0.7 }}>{c.name}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
