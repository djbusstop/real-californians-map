"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Sidebar from "@/components/Sidebar";
import { COLORS } from "@/lib/colors";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export type Scores = Record<string, Record<string, number>>;

export interface Subculture {
  id: string;
  name: string;
  vibe: string;
}

const EMPTY_FC: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

// Only cohorts present in subcultures.yaml's active set should appear here.
// Sidelined cohorts live in data-pipeline/subcultures_library.yaml; their
// COLORS entries are deliberately left in lib/colors.ts so reviving a
// cohort is just: move it back into subcultures.yaml, add it here, rerun.
const SUBCULTURES: Subculture[] = [
  { id: "teen_boy", name: "Teen boy", vibe: "halo with the headset on, skateboard in the garage, mom does carpools, dad's working late" },
  { id: "younger_sister", name: "Younger sister", vibe: "wants a horse but doesn't actually like the riding lessons. polly pockets. her brother picks what's on tv." },
];

export default function Home() {
  const [scores, setScores] = useState<Scores | null>(null);
  const [pumaGeo, setPumaGeo] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selected, setSelected] = useState<string[]>(() =>
    SUBCULTURES.map((s) => s.id)
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    if (window.innerWidth < 768) setSidebarOpen(false);
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    Promise.all([
      fetch("/data/tract_scores.json").then((r) => {
        if (!r.ok) throw new Error(`tract_scores.json: ${r.status}`);
        return r.json();
      }),
      fetch("/data/tracts_ca.geojson").then((r) => {
        if (!r.ok) throw new Error(`tracts_ca.geojson: ${r.status}`);
        return r.json();
      }),
    ])
      .then(([s, g]) => {
        setScores(s);
        setPumaGeo(g);
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // Clear in one state update rather than fanning out N toggle calls.
  // The latter relies on React's batching to compose correctly and
  // forces the dot useMemo and source.setData to run N times instead
  // of once on what is conceptually a single user action.
  const clear = () => setSelected([]);

  if (loadError) {
    return (
      <div style={{ padding: 24 }}>
        <h1>Data not loaded</h1>
        <p>{loadError}</p>
        <p>
          From <code>web/</code> run <code>npm run sync-data</code> to copy
          pipeline outputs into <code>public/data/</code>.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar
        subcultures={SUBCULTURES}
        selected={selected}
        onToggle={toggle}
        onClear={clear}
        scores={scores}
        isMobile={isMobile}
        open={sidebarOpen}
      />
      {isMobile && sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            zIndex: 15,
          }}
        />
      )}
      {isMobile && (
        <button
          onClick={() => setSidebarOpen((v) => !v)}
          aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
          style={{
            position: "fixed",
            top: 12,
            left: sidebarOpen ? 332 : 12, // sits beside the sidebar (320px wide) when open
            zIndex: 30,
            width: 38,
            height: 38,
            borderRadius: 6,
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            cursor: "pointer",
            fontSize: 18,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
            transition: "left 250ms ease",
          }}
        >
          {sidebarOpen ? "✕" : "☰"}
        </button>
      )}
      <div style={{ flex: 1, position: "relative" }}>
        <MapView
          geojson={pumaGeo ?? EMPTY_FC}
          scores={scores ?? {}}
          selectedIds={selected}
        />
        {isMobile && selected.length > 0 && (
          <div
            onClick={() => setSidebarOpen(true)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setSidebarOpen(true);
              }
            }}
            aria-label="Open cohort sidebar"
            style={{
              position: "fixed",
              bottom: 56,
              left: 12,
              zIndex: 10, // below sidebar (z-index 20) so it's hidden when sidebar opens
              background: "rgba(255,255,255,0.96)",
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              padding: "8px 10px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
              fontSize: 11,
              maxWidth: "65vw",
              cursor: "pointer",
            }}
          >
            {selected.map((id) => {
              const sub = SUBCULTURES.find((s) => s.id === id);
              const color = COLORS[id] ?? "#7eaaff";
              return (
                <div
                  key={id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "1px 0",
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: 4,
                      background: color,
                      flexShrink: 0,
                    }}
                  />
                  <span>{sub?.name ?? id}</span>
                </div>
              );
            })}
          </div>
        )}
        {(!scores || !pumaGeo) && (
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
            Loading data…
          </div>
        )}
      </div>
    </div>
  );
}
