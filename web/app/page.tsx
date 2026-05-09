"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Sidebar from "@/components/Sidebar";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export type Scores = Record<string, Record<string, number>>;

export interface Subculture {
  id: string;
  name: string;
  vibe: string;
}

const EMPTY_FC: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const SUBCULTURES: Subculture[] = [
  { id: "queer_leftist", name: "Queer leftist", vibe: "urban, partnered, helping profession, transit/walk/bike" },
  { id: "married_gays", name: "Married gays", vibe: "married, same-sex, of any description" },
  { id: "bilingual_baddie", name: "Bilingual baddies", vibe: "she's bilingual, she has to work, and she's fine with it DAMN" },
  { id: "crumbl_cookie_couple", name: "Crumbl cookie couple", vibe: "just a normal married couple, new homeowners, two cars, Taylor Swift and golf" },
  { id: "wino", name: "Winos", vibe: "50-75 business-owner homeowner, multiple cars, teen kids around, grills and chills" },
  { id: "hill_people", name: "Toothless hill people", vibe: "acid-dropping libertarian racists with more guns than teeth. they own the weed farms." },
  { id: "stupid_guy", name: "Stupid guys", vibe: "no diploma, gas station/cashier work, never married, trailer or parents' house" },
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
