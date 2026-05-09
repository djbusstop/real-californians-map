# Real Californians: data pipeline

Fetches ACS PUMS for California, scores each record against the subcultures defined in `subcultures.yaml`, distributes scores to tracts, and outputs JSON the Next.js app reads.

## Setup

```sh
cd data-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```sh
python pipeline.py
```

First run downloads the CA PUMS CSV files directly from the Census FTP (~80MB persons + ~25MB housing for the 1-year 2023 sample) plus the PUMA boundary shapefile. Total first-run time: 2-5 minutes depending on connection. Subsequent runs read the cached parquet and finish in seconds.

Earlier versions used the Census Data API but it returned intermittent 500 errors on small queries. Direct CSV download is more reliable. To upgrade to the larger 5-year sample later, change `/1-Year/` to `/5-Year/` in the URLs at the top of `pipeline.py`.

## Outputs

In `./data/`:

- `pums_ca.parquet`: merged person + household records with weights. Reusable for any subsequent analysis.
- `pumas_ca.geojson`: 2020-vintage PUMA boundaries for California.
- `scores.json`: `{ puma_code: { subculture_id: weighted_population } }`. The Next.js app reads this.
- `summary.json`: per-subculture weighted totals + sanity check (CA population should be ~39M).

## Editing subcultures

`subcultures.yaml` is the source of truth for the 8 v0.2 subcultures. To add a new one:

1. Add a YAML entry with `id`, `name`, `vibe`, `vector`, `proxy_gap`.
2. Re-run `python pipeline.py`. Cached PUMS data is reused; only the scoring pass re-runs.
3. The new subculture appears in `scores.json` automatically.

## Operators in vector conditions

- `eq` — field equals value
- `in` — field is in `[values]`
- `range` — field in `[lo, hi]`
- `gte` / `lte` — field >= / <= value
- `industry_naics` — field is an INDP code mapping to NAICS sector(s) (e.g. `[11]` for agriculture)
- `occupation_soc_major` — field is an OCCP code mapping to SOC major group(s) (e.g. `[15, 17]` for computer/math + engineering)
- `occupation_soc_minor` — field is an OCCP code prefix matching SOC minor group(s)
- `spanish` — language at home is Spanish (LANP code 1200)
- `percentile_gte` — field is >= the Nth percentile of the column

`required: true` on a condition makes it a hard filter (record scores 0 if not satisfied).

## Known gaps in v0

- Same-sex household indicator (`SAME_SEX`) is currently a stub. Real implementation needs to derive from the `RELP` (relationship to householder) variable plus householder/spouse `SEX`. The `queer leftist` subculture will return 0 scores until this is wired in.
- `industry_naics` and `occupation_soc_major` use coarse approximations of the PUMS code-to-sector mapping. Validate against PUMS code lists once data is live.
- Normie is computed as similarity to the modal household, using a small set of fields (age decade, tenure, household type, marital status, education). May want to expand or change definition once you see results.

## Validating results

After the first run, sanity-check `summary.json`:

- `total_weighted_population` should be roughly 39 million (the population of California).
- `puma_count` should be roughly 265.
- `per_subculture_weighted_total` for each subculture should be a plausible fraction of CA's population (most should be hundreds of thousands to a few million).

If a subculture's total is suspiciously near zero, the proxy is probably broken (likely a code mapping issue). Open `pums_ca.parquet` in a notebook to investigate.

## Where this fits in the project

```
[ Census API ]  →  [ pipeline.py ]  →  [ data/scores.json ]  →  [ Next.js app ]
                                        [ data/pumas.geojson ]
```

Pipeline is the one place that touches raw PUMS. Next.js only ever reads the small JSON output. This separation keeps the runtime fast and the data layer reproducible.
