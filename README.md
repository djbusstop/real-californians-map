# Where Real Californians Live

An interactive web map of California subcultures, modeled from American Community Survey (ACS) data via configurable proxy vectors. Each subculture is a curated cultural archetype defined as a weighted combination of census variables. The map renders the geographic concentration of each subculture as dots inside California census tracts.

The project has two layers: an editorial layer (the subculture definitions, which are subjective and arguable) and an analytical layer (how those definitions are scored against census data, which is reproducible). The editorial layer is open in `data-pipeline/subcultures.yaml`; the analytical layer is documented in [METHODOLOGY.md](./METHODOLOGY.md).

## How it's built

`data-pipeline/` is a Python script that fetches Census PUMS records, scores them against the subcultures defined in `subcultures.yaml`, distributes scores to tracts via small-area estimation, and writes JSON outputs.

`web/` is a Next.js app that reads those outputs and renders them as a dot-density map with MapLibre GL.

## Quick start

You'll need Python 3.10+ and Node 18+.

**1. Run the pipeline.** From `data-pipeline/`:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python pipeline.py
```

First run takes 2-5 minutes (downloads CA PUMS CSVs, tract boundaries, ACS marginals). Subsequent runs use the cache and finish in seconds.

**2. Sync data to the web app and run it.** From `web/`:

```sh
npm install
npm run sync-data
npm run dev
```

Then open http://localhost:3000.

## Editing subcultures

Open `data-pipeline/subcultures.yaml` and edit any vector. Every condition has a field, an operator, a value, and a weight. `required: true` makes a condition a hard gate; otherwise it's a soft signal that nudges the score. Re-run `python pipeline.py` (uses cached data, ~10 seconds) and `npm run sync-data` to see your changes.

`data-pipeline/FIELDS.md` is the reference for every census variable available, including the ones not currently used.

### One-shot rebuild + run (from `web/`)

After editing the YAML, this single command re-runs the pipeline, syncs the outputs into the web app, and starts the dev server:

```sh
(cd ../data-pipeline && source .venv/bin/activate && python pipeline.py) && npm run sync-data && npm run dev
```

The subshell `( ... )` keeps the `cd` local to the pipeline run so you stay in `web/`. The `&&` chain ensures each step only runs if the previous one succeeded.

## Methodology

See [METHODOLOGY.md](./METHODOLOGY.md) for the full description of data sources, scoring, small-area estimation, dot density rendering, and limitations.

## Data sources

- ACS Public Use Microdata Sample (PUMS), 2023 1-Year, California
- ACS 5-Year Detailed Tables, 2023, tract level (for marginals)
- TIGER/Line shapefiles for census tract boundaries
- Census Bureau tract-to-PUMA crosswalk
- OpenFreeMap (positron style) for the basemap

All Census data is free and public.

## License

MIT. See [LICENSE](./LICENSE).
