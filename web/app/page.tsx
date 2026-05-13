import { readFile } from "node:fs/promises";
import path from "node:path";

import library from "@/lib/library.json";
import type { Cohort } from "@/lib/types";
import MapView from "@/components/MapView";

const COHORTS_DIR = path.join(process.cwd(), "public", "data", "cohorts");

async function loadCohort(c: (typeof library)[number]): Promise<Cohort | null> {
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
