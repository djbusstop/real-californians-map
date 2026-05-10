# Real Californians: data pipeline

Fetches ACS PUMS for California, scores each record against the cohorts defined in `subcultures.yaml`, distributes scores to census tracts via Fay-Herriot small-area estimation, and outputs JSON the Next.js app reads.

For the methodology (cohort definitions, scoring, small-area model, diagnostics, limitations), see [METHODOLOGY.md](../METHODOLOGY.md) at the project root.

## Setup

```sh
cd data-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ is required.

## Run

```sh
python pipeline.py
```

First run downloads the CA PUMS 5-Year sample directly from the Census FTP (~400MB persons + ~120MB housing), the TIGER tract shapefile, and ACS 5-Year tract marginals. Total first-run time: 10-20 minutes depending on connection. Subsequent runs read the cached parquet and complete the scoring + small-area pass in well under a minute.

The 5-Year sample is ~5% of California (vs. ~1% for the 1-Year), so cohort counts are far more stable and Fay-Herriot fold failures effectively disappear at the cohort sizes we care about.

## Outputs

In `./data/`:

- `pums_ca.parquet` — merged person + household records with the 80 replicate weights. Reusable for any subsequent analysis.
- `tracts_ca.geojson` — TIGER census tract boundaries for California.
- `tract_scores.json` — `{ tract_geoid: { cohort_id: weighted_population } }`. The Next.js app reads this.
- `model_summaries.json` — per-cohort Fay-Herriot diagnostics: σ²_u, σ²_e, EBLUP shrinkage γ, ridge λ, LOOCV R², bootstrap CI half-widths, Conley HAC SEs, Moran's I on residuals, VIFs.
- `puma_scores.json` — intermediate PUMA-level cohort scores prior to tract distribution.

`tract_scores.json` and `tracts_ca.geojson` are the two files the web app needs; `npm run sync-data` from `web/` copies them into `web/public/data/`.

## Editing cohorts

`subcultures.yaml` is the source of truth. Each cohort has:

- `id`, `name`, `vibe` — display metadata
- `vector` — list of conditions, each with `field`, `op`, `value`, `weight`, optional `required: true`
- `tract_marginals` — list of ACS tract-level table codes the small-area model uses as the marginal for this cohort

To add or modify a cohort, edit the YAML and re-run `python pipeline.py`. The cached PUMS parquet is reused; only the scoring + small-area pass re-runs.

`FIELDS.md` is the reference for every PUMS variable currently loaded into the DataFrame.

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

## Validating results

After the run, sanity-check `model_summaries.json`:

- `puma_n_records` should be ~265 (CA PUMA count) for any cohort that scores broadly.
- `tract_n_records` should be ~9,000 (CA tract count).
- Per-cohort `weighted_total` should be a plausible fraction of CA's ~39M population.
- `loocv_r2` ideally > 0.05; lower indicates the small-area model is doing little better than the cohort mean.
- `loocv_failed_splits` should be 0 with the 5-Year sample. Non-zero means some folds collapsed to the y_mean fallback (see methodology).
- `morans_i_p_value` near 0 with positive `morans_i` indicates residual spatial structure the model did not capture — informational, not necessarily a problem.

If a cohort's `weighted_total` is suspiciously near zero, the proxy is probably broken (likely a code mapping issue or a hard gate that no record satisfies). The pipeline now warns when a YAML field is not present in the PUMS columns and when an ACS tract marginal call returns all zeros.

## Caching

The pipeline cache lives in `data-pipeline/cache/` (raw downloads) and `data-pipeline/data/` (derived parquet + outputs). The `pums_ca.parquet` cache validates against the full current `PERSON_VARS + HOUSING_VARS + PWGTP1..80` column list on every run; if any column the YAML or pipeline expects is missing, the cache is regenerated.

To force a full rebuild, delete `data-pipeline/data/pums_ca.parquet` and the relevant files in `data-pipeline/cache/`.

## Where this fits in the project

```
[ Census PUMS + ACS ]  →  [ pipeline.py ]  →  [ data/tract_scores.json   ]  →  [ Next.js app ]
                                              [ data/tracts_ca.geojson   ]
```

The pipeline is the only place that touches raw PUMS. The Next.js app only ever reads the small JSON outputs. This separation keeps the runtime fast and the data layer reproducible.
