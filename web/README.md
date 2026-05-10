# Real Californians: web app

The Next.js app that renders the subculture cohort scores as dot density on California census tracts. The data comes from `data-pipeline/`, which produces the JSON outputs this app reads.

## First-run setup

Requires Node 18+ and npm. From this folder (`web/`):

```sh
npm install
npm run sync-data   # copies pipeline outputs into public/data/
npm run dev
```

Then open http://localhost:3000.

`sync-data` copies `tract_scores.json` and `tracts_ca.geojson` from `../data-pipeline/data/`. Re-run `sync-data` whenever you re-run the pipeline.

After editing `subcultures.yaml`, the typical iteration loop from this folder is:

```sh
(cd ../data-pipeline && source .venv/bin/activate && python pipeline.py) && npm run sync-data && npm run dev
```

## What the app does

- Loads cohort tract scores and California tract geometry on first paint.
- Renders each cohort as random dots inside the tracts where it concentrates. One dot represents about 20 weighted cohort-equivalent people.
- Sidebar lists the named cohorts; click to toggle each on or off. Multiple cohorts can render simultaneously, each with its own color.
- Mobile-responsive layout: sidebar slides in and out via a toggle button at narrow viewports.
- Map is clipped to California's land area, so dots never fall in the ocean or the Bay.
- OpenFreeMap positron basemap underneath the dots. City and place-name labels are layered above the dots so they remain readable.

## Configurable knobs

- `DOTS_PER_UNIT` in `components/MapView.tsx` controls dot density. Currently 20 (one dot ≈ 20 weighted people). Lower = more dots = denser visual.
- The zoom-radius interpolation expression in `components/MapView.tsx` controls dot size at each zoom level. Edit the array of `(zoom, radius)` pairs inside the `circle-radius` paint property.
- `COLORS` in `lib/colors.ts` is the single source of truth for cohort colors. Edit one map there and the sidebar, dots, and mobile legend all update consistently.
- Cohort definitions, trait vectors, and tract marginals live in `../data-pipeline/subcultures.yaml`. Edit there, re-run the pipeline, re-sync data.

## File structure

```
app/
  layout.tsx           Root layout
  page.tsx             Main page; cohort selection state, mobile-responsive layout
  globals.css          Minimal styles
components/
  MapView.tsx          MapLibre map with dot density layer
  Sidebar.tsx          Cohort browser with name + vibe
lib/
  colors.ts            Cohort color palette
utils/
  dotgen.ts            Random-point generation inside tract polygons (turf-based)
public/
  data/                (synced from data-pipeline/data/)
    tract_scores.json
    tracts_ca.geojson
```

## Methodology

For the analytical layer (cohort definitions, scoring, small-area estimation, diagnostics, limitations), see [METHODOLOGY.md](../METHODOLOGY.md) at the project root.
