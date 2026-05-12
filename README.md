# Where Real Californians Live

An interactive web map of California subcultures, modeled from American Community Survey (ACS) data via configurable proxy vectors. Each subculture is a curated cultural archetype defined as a weighted combination of census variables. The map renders the geographic concentration of each subculture as dots inside California census tracts.

The project has two layers: an editorial layer (the subculture definitions, which are subjective and arguable) and an analytical layer (how those definitions are scored against census data, which is reproducible). The editorial layer is open in `web/lib/library.json`; the analytical layer is documented in [METHODOLOGY.md](./METHODOLOGY.md).

## How it's built

`data-pipeline/` is a Python service. `data_prep.py` builds the PUMS parquet artifact once; `server.py` runs a FastAPI service that scores cohort definitions on demand and returns tract-level scores. `scripts/generate_clipped_tracts.py` produces the tract GeoJSON the frontend renders.

`web/` is a Next.js app that ships the cohort library, fetches tract scores from the FastAPI service per cohort, and renders results as a dot-density map with MapLibre GL. Users can also author ad-hoc cohorts in a builder modal; those POST to the same `/score` endpoint.

## Quick start

You'll need Python 3.10+ and Node 18+.

**1. Build the PUMS parquet and clipped tracts.** From `data-pipeline/`:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python data_prep.py
python scripts/generate_clipped_tracts.py
```

`data_prep.py` downloads the CA PUMS 5-Year CSVs (~520 MB person + housing) and writes `cache/pums_ca.parquet`. First run takes 10-20 minutes; subsequent runs reuse the cache.

`scripts/generate_clipped_tracts.py` downloads the TIGER tract shapefile and the cartographic boundary state file, clips tracts against California's land polygon, and writes `web/public/data/tracts_ca.geojson` directly.

**2. Run the scoring service.** From `data-pipeline/`:

```sh
uvicorn server:app --host 0.0.0.0 --port 8000
```

The server loads the parquet, tract↔PUMA crosswalk, spatial weights, PUMA centroids, and tract population marginal at startup (~5-15s with warm caches), then serves `POST /score`. Responses are cached on disk by content hash.

**3. Run the web app.** From `web/`:

```sh
npm install
npm run dev
```

Then open http://localhost:3000.

## Editing subcultures

Open `web/lib/library.json` and edit any vector. Every condition has a field, an operator, a value, and a weight. `required: true` makes a condition a hard gate; otherwise it's a soft signal that nudges the score. Reload the page; the frontend POSTs each cohort to the scoring service and renders the response. Re-scoring an unchanged cohort is instant (content-hash cached server-side).

`data-pipeline/pums_fields.yaml` is the catalog of every census variable the pipeline loads, with inline comments describing each. `docs/fields.md` is a longer-form reference.

## Methodology

See [METHODOLOGY.md](./METHODOLOGY.md) for the full description of data sources, scoring, small-area estimation, dot density rendering, and limitations.

## Data sources

- ACS Public Use Microdata Sample (PUMS), 2023 5-Year, California (~5% pooled sample, ~2M person records)
- ACS 5-Year Detailed Tables, 2023, tract level (for marginals, fetched on demand per cohort)
- TIGER/Line shapefiles for census tract and PUMA boundaries
- Census Bureau tract-to-PUMA crosswalk
- OpenFreeMap (positron style) for the basemap

All Census data is free and public.

## License

MIT. See [LICENSE](./LICENSE).
