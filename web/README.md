# Real Californians: web app

Next.js app that renders the subculture scores as a choropleth on California's PUMAs. Sister to `/data-pipeline/`, which produces the data this app reads.

## First-run setup

Requires Node 18+ and npm. From this folder (`web/`):

```sh
npm install
npm run sync-data   # copies pipeline outputs into public/data/
npm run dev
```

Then open http://localhost:3000.

`sync-data` copies `scores.json`, `pumas_ca.geojson`, and `summary.json` from `../data-pipeline/data/`. Re-run `sync-data` whenever you re-run the pipeline.

## What's in v0

- 281 California PUMAs rendered as faint outlines.
- Dot density layer: random points scattered inside each PUMA, count proportional to that PUMA's score for the selected subculture.
- Sidebar with the 9 subcultures from `subcultures.yaml`.
- Click a subculture, dots and color regenerate.
- Hover a PUMA to see its name and score.

Tuning knob: `DOTS_PER_UNIT` in `components/MapView.tsx` controls density. Lower = more dots = denser visual but slower regeneration. Default 500, which gives ~15-30k dots per subculture and feels smooth.

## Known caveats (read before judging the data)

- **Scores are inflated.** Soft scoring without gates means a person can partially fit several subcultures, so per-subculture totals sum to ~2.5× California's population. The relative shape between PUMAs is meaningful; the absolute numbers are not.
- **Queer leftist is currently broken.** The `SAME_SEX` household indicator is a stub set to 0 in the pipeline. The map still renders something for this subculture, but it's measuring "young + educated + urban + renter + helping profession," not actual queer households. Will be wired up in a follow-up.
- **No tile basemap.** Polygons are on a flat dark background. We can layer in OpenFreeMap or similar later if you want geographic context (city labels, coastline).
- **No dot density yet.** Choropleth was the fastest way to see the data shape. Dot density is a possible next step once proxies are tuned.

## Adding a tile basemap later

Drop in OpenFreeMap (free, no API key) by replacing the `style: { ... }` literal in `components/MapView.tsx` with:

```ts
style: "https://tiles.openfreemap.org/styles/positron"
```

Positron is a clean grayscale style that works as a backdrop for data overlays.

## File structure

```
app/
  layout.tsx           Root layout
  page.tsx             Main page with subculture state
  globals.css          Minimal styles
components/
  Sidebar.tsx          Subculture browser
  MapView.tsx          MapLibre choropleth
public/
  data/                (synced from data-pipeline/data/)
    scores.json
    pumas_ca.geojson
    summary.json
```
