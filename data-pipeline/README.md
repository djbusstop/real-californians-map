# Real Californians: data pipeline

The Python side of the project. Three responsibilities:

1. **Build the PUMS parquet** (`data_prep.py`). Downloads CA PUMS 5-Year person + household CSVs, joins them on `SERIALNO`, derives the `SAME_SEX` household flag, and persists a single parquet to `cache/pums_ca.parquet`.
2. **Score cohorts on demand** (`server.py` + `service.py` + `scoring.py` + `sae.py`). FastAPI service that takes a cohort definition over HTTP and returns tract-level scores plus the raw statistical diagnostics from the model. Responses are content-hash cached on disk.
3. **Generate clipped tract geometry** (`scripts/generate_clipped_tracts.py`). One-off script that fetches the TIGER tract shapefile and the cartographic boundary state file, intersects tracts with California's land polygon, and writes the result to `web/public/data/tracts_ca.geojson` for the frontend to render.

For the methodology (cohort definitions, scoring, small-area model, diagnostics, limitations), see [METHODOLOGY.md](../METHODOLOGY.md) at the project root.

## Setup

```sh
cd data-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ is required.

## First-run build

```sh
python data_prep.py
python scripts/generate_clipped_tracts.py
```

`data_prep.py` downloads the CA PUMS 5-Year sample directly from the Census FTP (~400 MB person + ~120 MB housing) and writes the joined parquet. Total first run: 10-20 minutes depending on connection. Subsequent invocations validate the cached parquet column set; if a new field has been added to `pums_fields.yaml` and is referenced by a library cohort, the parquet is regenerated.

The 5-Year sample is ~5% of California (vs. ~1% for the 1-Year), so cohort counts are stable and Fay-Herriot fold failures effectively disappear at the cohort sizes we care about.

`scripts/generate_clipped_tracts.py` writes directly to `web/public/data/tracts_ca.geojson`. Run it whenever you want fresh tract boundaries (e.g. a new TIGER vintage).

## Running the scoring service

```sh
uvicorn server:app --host 0.0.0.0 --port 8000
```

Startup loads the PUMS DataFrame, the tract↔PUMA crosswalk, PUMA spatial weights and centroids, and the tract population marginal. With warm caches this is ~5-15 seconds; cold-start (first run after build) is dominated by the PUMS DataFrame load.

The endpoint contract lives in [`docs/cohort_api_spec.md`](../docs/cohort_api_spec.md).

## Cache layout

All derived artifacts live in `data-pipeline/cache/`:

- `pums_ca.parquet` — merged person + household records with the 80 replicate weights, plus the derived `SAME_SEX` flag. Reusable for any subsequent analysis.
- `pums_persons_ca.zip`, `pums_housing_ca.zip` — raw Census FTP downloads, kept so re-parsing doesn't re-download.
- `puma_shp/`, `state_shp/`, `tract_shp/` — extracted TIGER and cartographic-boundary shapefiles.
- `acs_tract_*.json` — per-variable ACS tract marginal cache, fetched by `sae.fetch_acs_tract_marginal` on first use and reused across cohorts within a process.
- `tract_puma_crosswalk_ca.csv` — Census tract-to-PUMA crosswalk, filtered to CA.

The cohort response cache lives in `cohort_cache/response_<hash>.json` (one file per unique cohort definition).

The parquet validates against the full current `PERSON_VARS + HOUSING_VARS + PWGTP1..80` column list on every load; if any column the library or pipeline expects is missing, the parquet is regenerated. To force a full rebuild, delete `cache/pums_ca.parquet` (or the entire `cache/` folder).

## Editing cohorts

`../web/lib/library.json` is the source of truth. Each cohort has:

- `id`, `name`, `vibe` — display metadata
- `vector` — list of conditions, each with `field`, `op`, `value`, `weight`, optional `required: true`
- `tract_marginals` — list of ACS tract-level table codes the small-area model uses as the marginal for this cohort
- `threshold` — optional override for the per-cohort membership threshold (default 0.5)

The frontend POSTs each cohort to the running scoring service. No re-run of `data_prep.py` is needed after editing the library; only `pums_fields.yaml` changes (adding a new field referenced by a cohort) trigger a parquet rebuild on next service start.

`../docs/fields.md` is the reference for every PUMS variable currently loaded into the DataFrame.

## Operators in vector conditions

- `eq` — field equals value
- `in` — field is in `[values]`
- `range` — field in `[lo, hi]`
- `gte` / `lte` — field >= / <= value
- `industry_naics` — field is an INDP code mapping to NAICS sector(s)
- `occupation_soc_major` — field is an OCCP code mapping to SOC major group(s)
- `occupation_soc_minor` — field is an OCCP code prefix matching SOC minor group(s)
- `spanish` — language at home is Spanish (LANP code 1200)
- `percentile_gte` — field is >= the Nth percentile of the column

`required: true` on a condition makes it a hard filter (record scores 0 if not satisfied). Use this for identity-defining gates (e.g., `SAME_SEX = 1` for the queer cohort). Soft signals belong without `required` — they nudge the score for character flavor without excluding records.

## Module layout

```
data_prep.py            PUMS fetch + parquet build + PUMA/tract geometry
                        helpers + tract↔PUMA crosswalk + field catalog loader
scoring.py              Per-record scoring (operators, gates, fit), threshold-
                        based membership, PUMA aggregation with SDR variance
sae.py                  Small-area estimation: ACS marginal fetching,
                        ridge+NNLS, Fay-Herriot EBLUP, Conley spatial HAC,
                        bootstrap CIs, Moran's I, MOE-weighted within-PUMA
                        raking
service.py              Orchestrator: ServerState (long-lived process state),
                        canonical_cohort_hash, score_one_cohort
server.py               FastAPI HTTP layer
pums_fields.yaml        PUMS field catalog with inline-comment descriptors
scripts/
  generate_clipped_tracts.py    Tract GeoJSON for the frontend
tests/
  smoke_latency.py      End-to-end /score latency check
```

## Where this fits in the project

```
[ Census PUMS + ACS ]  →  [ data_prep.py builds parquet ]
[ TIGER + CB tracts ]  →  [ scripts/generate_clipped_tracts.py → web/public/data/tracts_ca.geojson ]
                                            ↓
                          [ server.py / service.py / scoring.py / sae.py ]
                                            ↓ POST /score per cohort
                                  [ Next.js app renders dots ]
```

`data_prep.py` is the only place that touches raw PUMS. The FastAPI service is the only place that runs the SAE. The Next.js app only ever consumes the `/score` response and the clipped tract GeoJSON.
