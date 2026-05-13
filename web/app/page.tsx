import { readFile } from "node:fs/promises";
import path from "node:path";

import library from "@/lib/library.json";
import { COHORT_API_BASE } from "@/lib/constants";
import type { Cohort } from "@/lib/types";
import MapView from "@/components/MapView";

const COHORTS_DIR = path.join(process.cwd(), "public", "data", "cohorts");

async function loadFromDisk(
  c: (typeof library)[number],
): Promise<Cohort | null> {
  try {
    const text = await readFile(
      path.join(COHORTS_DIR, `${c.id}.json`),
      "utf-8",
    );
    return { ...JSON.parse(text), color: c.color };
  } catch {
    return null;
  }
}

async function loadFromApi(
  c: (typeof library)[number],
): Promise<Cohort | null> {
  try {
    const res = await fetch(`${COHORT_API_BASE}/score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
      cache: "no-store",
    });
    if (!res.ok) return null;
    return { ...(await res.json()), color: c.color };
  } catch {
    return null;
  }
}

async function loadCohort(c: (typeof library)[number]): Promise<Cohort | null> {
  return (await loadFromDisk(c)) ?? (await loadFromApi(c));
}

export default async function Home() {
  const loaded = await Promise.all(library.map(loadCohort));
  const cohorts = loaded.filter((c): c is Cohort => c !== null);

  return (
    <main
      style={{
        width: "100vw",
        height: "100vh",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <MapView cohorts={cohorts} />
    </main>
  );
}
