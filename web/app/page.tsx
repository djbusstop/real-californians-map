// Server component. Data fetching happens here at request time:
//   1. Read the cohort library JSON statically (shipped in this repo)
//   2. POST each cohort to the scoring API in parallel via Promise.all
//   3. Each response carries inline tract_scores + stats
//   4. Attach the library entry's color onto each response (the backend
//      treats color as presentation-only and does not echo it)
//   5. Pass cohorts to the (client) MapView
//
// Why cohorts server-side but geometry client-side: cohort responses
// are small (~1MB inlined total) and the API round-trip is the slow
// part, which the server can absorb while keeping HTML payload small.
// The tracts geometry (~85MB) is fetched client-side because static
// assets cache aggressively in the browser and inlining it would
// balloon the HTML response on every request.
//
// The cohort API URL is configurable via COHORT_API_BASE (no
// NEXT_PUBLIC_ prefix needed since the call is server-to-server).

import library from "@/lib/library.json";
import { COHORT_API_BASE } from "@/lib/constants";
import type { Cohort } from "@/lib/types";
import MapView from "@/components/MapView";

async function scoreLibraryCohort(
  cohort: (typeof library)[number],
): Promise<Cohort> {
  const res = await fetch(`${COHORT_API_BASE}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cohort),
    // Backend cache is content-hash keyed; second hit is sub-50ms.
    // Skipping Next.js fetch caching avoids a second cache layer that
    // would need its own invalidation story.
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      `POST /score (${cohort.id}) failed: HTTP ${res.status} ` +
        `${await res.text().catch(() => "<no body>")}`,
    );
  }
  const data = await res.json();
  // The backend doesn't return `color` (it's presentation, never part of
  // the canonical hash). We attach it here from the library entry so the
  // map has everything it needs to render in one prop.
  return { ...data, color: cohort.color };
}

export default async function Home() {
  const cohorts = await Promise.all(library.map(scoreLibraryCohort));

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
