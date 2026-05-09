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
  { id: "bilingual_baddie", name: "Bilingual baddies", vibe: "she's bilingual, she has to work, and she's fine with it DAMN" },
  { id: "crumbl_cookie_couple", name: "Crumbl cookie couple", vibe: "just a normal married couple, new homeowners, two cars, Taylor Swift and golf" },
  { id: "wino", name: "Winos", vibe: "50-75 business-owner homeowner, multiple cars, teen kids around, grills and chills" },
  { id: "hill_people", name: "Toothless hill people", vibe: "rural, low-educated, lives on land, low income, wood-heated, isolated" },
  { id: "stupid_guy", name: "Stupid guys", vibe: "no diploma, gas station/cashier work, never married, trailer or parents' house" },
];

export default function Home() {
  const [scores, setScores] = useState<Scores | null>(null);
  const [pumaGeo, setPumaGeo] = useState<GeoJSON.FeatureCollection | null>(null);
  const [selected, setSelected] = useState<string[]>(() =>
    SUBCULTURES.map((s) => s.id)
  );
  const [loadError, setLoadError] = useState<string | null>(null);

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
      />
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
