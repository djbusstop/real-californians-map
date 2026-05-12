# Real Californians: web app

The Next.js app. Renders the subculture cohorts as dot density on California census tracts. The cohort library (`lib/library.json`) ships with the app; the actual tract scores come from the FastAPI scoring service in `../data-pipeline/`.

## First-run setup

Requires Node 18+ and npm. From this folder (`web/`):

```sh
npm install
npm run dev
```

Then open http://localhost:3000.

The page expects two things to exist:

- `public/data/tracts_ca.geojson` — clipped tract boundaries, written by `../data-pipeline/scripts/generate_clipped_tracts.py`.
- A running scoring service at `http://localhost:8000` (default) — started with `uvicorn server:app` from `../data-pipeline/`.

If the service isn't running, the map shows an error boundary with a hint to start it. If the tract GeoJSON is missing, the map renders empty.

## What the app does

- Reads `lib/library.json` for the cohort definitions and metadata.
- Loads the tract GeoJSON on first paint.
- POSTs each cohort definition to `POST /score` on the scoring service; the response carries tract-level scores plus the model's raw statistical diagnostics. Responses are content-hash cached server-side, so refreshing is fast.
- Renders each cohort as random dots inside the tracts where it concentrates. One dot represents about 20 weighted cohort-equivalent people.
- Sidebar lists the cohorts; click to toggle each on or off. Multiple cohorts can render simultaneously, each with its own color.
- "+ new cohort" opens a builder modal where users can author an ad-hoc cohort. The modal posts to the same `/score` endpoint and renders the result on the map alongside the named cohorts.
- Mobile-responsive layout: sidebar slides in and out via a toggle button at narrow viewports.
- Map is clipped to California's land area, so dots never fall in the ocean or the Bay.
- OpenFreeMap positron basemap underneath the dots. City and place-name labels are layered above the dots so they remain readable.

## Configurable knobs

- `DOTS_PER_UNIT` in `components/MapView.tsx` controls dot density. Currently 20 (one dot ≈ 20 weighted people). Lower = more dots = denser visual.
- The zoom-radius interpolation expression in `components/MapView.tsx` controls dot size at each zoom level. Edit the array of `(zoom, radius)` pairs inside the `circle-radius` paint property.
- `COLORS` in `lib/colors.ts` is the single source of truth for cohort colors. Edit one map there and the sidebar, dots, and mobile legend all update consistently.
- `COHORT_API_BASE` in `lib/constants.ts` points the frontend at the scoring service URL.
- Cohort definitions, trait vectors, and tract marginals live in `lib/library.json`. Edit there and reload; the frontend re-posts to the service and the response renders.

## File structure

```
app/
  layout.tsx           Root layout
  page.tsx             Main page (server component); fetches cohort scores
  globals.css          Minimal styles
components/
  MapView.tsx          MapLibre map with dot density layer + legend
  CohortBuilder.tsx    Modal form for authoring ad-hoc cohorts
  Sidebar.tsx          Cohort browser
lib/
  library.json         Cohort library (source of truth)
  colors.ts            Cohort color palette
  constants.ts         API base URL, color constants
  types.ts             Shared types
utils/
  dotgen.ts            Random-point generation inside tract polygons (turf-based)
public/
  data/
    tracts_ca.geojson  Written by data-pipeline/scripts/generate_clipped_tracts.py
```

## Methodology

For the analytical layer (cohort definitions, scoring, small-area estimation, diagnostics, limitations), see [METHODOLOGY.md](../METHODOLOGY.md) at the project root.
