# Changelog

All notable changes to this project are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.2.1] — 2026-05-10

A patch release. Fixes a silent field-rename bug in the year-built signal that had been zeroing the old-housing soft signals on multiple cohorts since the 5-Year switch, and adds a family-portrait cohort.

### Added

- `dad_2007` cohort: a family-portrait persona with a wealthy mid-life household envelope (property >$1M, 4+ bed, detached, 1990+ build, owned with mortgage, kids 6-17) and dad's life-stage signals (40-55, male, ever-married, bachelor's+, in labor force, $150k+ income, often works from home). Wired into the web app with a bronze (`#92400e`) dot color.

### Fixed

- **`YBL` → `YRBLT` field rename in 2023 5-Year PUMS.** PUMS now encodes year-built as `YRBLT` (decade-start year, e.g. 1939, 1970, 2000, 2020) rather than the older `YBL` decade-integer code. The pipeline still asked for `YBL`, so every YBL condition silently scored zero. This had been masking the old-housing signals on `queer_leftist`, `hill_people`, and was the cause of `dad_2007` having zero gate-passers entirely. Pipeline now requests `YRBLT` and all three cohorts have year-built conditions retranslated to the year-value scheme. Old housing cohorts (queer_leftist, hill_people) should look slightly more concentrated in their pre-1980 geographies after this fix.

### Changed

- `dad_2007` vector loosened during iteration: `ACR eq 2` (lot 1-9.99 ac) gate dropped entirely, build-year widened from 2000-2009 specifically to 1990+, after the original tight stack collapsed to zero gate-passers in CA PUMS.

### Removed

- `divorced_wine_mom` cohort — added during 0.2.0 development, then removed before this release. Net effect on the published cohort set: unchanged from 0.2.0.

## [0.2.0] — 2026-05-10

The methodology release. Reframed the project as a piece of speculative cartography in the spirit of Solnit's *Infinite City* and gave the analytical layer enough rigour to defend at academic standards. Replaced fuzzy-set scoring with threshold-based binary cohort membership so the headline estimand is a population total in the standard small-area-estimation sense rather than a fuzzy-set σ-count. Switched the rendering layer from PUMA-level choropleth to tract-level dot density. Cohort taxonomy revised down to six named archetypes.

### Added

- **Threshold-based cohort membership.** Per-cohort threshold τ ∈ (0, 1] applied to the continuous fit score yields a binary membership indicator per PUMS record. PUMA-level estimand is now `Σ member × PWGTP`, a well-defined weighted population total, fed unchanged into Fay-Herriot. Default τ = 0.5 declared in YAML `settings`, overridable per cohort. Earlier fuzzy-set scoring is retained as a within-cohort diagnostic ("weighted soft total") for transparency. Connects to standard practice in synthetic-population microsimulation (Beckman, Baggerly & McKay 1996; Williamson, Birkin & Rees 1998; Tanton & Edwards 2013) and to the operating-point selection problem in classifier evaluation (Hanley & McNeil 1982; Pepe 2003).
- Per-cohort scoring-stage diagnostics in `model_summaries.json`: threshold τ, weighted gate-pass count, weighted soft total, mean fit per member.
- Fay-Herriot small-area estimation with EBLUP shrinkage, Prasad-Rao 1990 method-of-moments σ²_u, and ridge-regularized synthetic component (Hoerl-Kennard 1970).
- Successive-difference replication (SDR) sampling-variance estimator using PUMS replicate weights PWGTP1..80, per Wolter 2007.
- Conley 1999 spatial HAC standard errors at a fixed 75 km Bartlett kernel.
- Non-parametric bootstrap percentile confidence intervals (Efron-Tibshirani 1993, 1000 iterations) on cohort tract scores.
- Moran's I residual diagnostics (Cliff & Ord 1981) on queen-contiguity PUMA neighbours.
- VIF multicollinearity diagnostics (Belsley, Kuh & Welsch 1980).
- LOOCV `λ` selection over a fixed grid, with per-λ failed-split tracking surfaced in `model_summaries.json`.
- Six named cohorts: queer leftist, married gays, bilingual baddie, Crumbl cookie couple, toothless hill people, crazy person on the bus.
- Mobile-responsive sidebar with slide-in toggle.
- `CHANGELOG.md`.

### Changed

- **Headline cohort estimand changed from fuzzy-set σ-count to weighted member count.** Tract values in `tract_scores.json` and dot density on the map now correspond to weighted counts of cohort members (under the threshold rule above), not weighted sums of similarity scores. The user-facing legend "1 dot ≈ 20 people" now maps to a real population quantity rather than a fuzzy-set cardinality.
- METHODOLOGY.md "Scoring" section rewritten as a three-stage rule (fit score → membership indicator → PUMA aggregation), with explicit framing of why this estimand is statistically well-formed for FH/SDR machinery.
- ACS PUMS source switched from 2023 1-Year (~1% sample) to 2023 5-Year (~5% pooled, ~2M person records). Cohort sample sizes are now stable enough that LOOCV fold failures effectively disappear at the cohort sizes we care about.
- Map rendering switched from PUMA-level choropleth to tract-level random-dot density (1 dot ≈ 20 weighted people).
- `subcultures.yaml` now distinguishes hard identity gates (`required: true`) from soft character signals.
- Project framing in `METHODOLOGY.md` rewritten to position the work as speculative cartography rather than empirical demography, and to honestly describe what the diagnostics can and cannot detect.
- Pipeline cache validation widened to check every column in `PERSON_VARS + HOUSING_VARS + PWGTP1..80`. Stale parquets that predate a column-list change now auto-regenerate instead of silently scoring conditions on absent fields as zero.
- Top-of-file imports replace function-level numpy/scipy imports.
- Magic numbers (LOOCV grid, Conley bandwidth, bootstrap iterations, VIF infinity threshold) promoted to module constants.

### Fixed

- Map dot layer no longer leaves stuck dots after "clear all" or rapid cohort toggling. The data-sync effect previously gated on `isStyleLoaded()`, which can flip false transiently during MapLibre tile work; updates queued onto `map.once("load", ...)` were silently dropped because `load` only fires on initial style load. Replaced with a `mapReady` state that flips true inside the load handler and is the sole gate.
- "Clear" button now does one `setSelected([])` rather than fanning out N toggles via `forEach`.
- ACS tract marginal fetch now warns and refuses to cache an all-zeros response (previously suggested by tract-level disclosure suppression on B16001 and B11009; replaced those tables with C16001 and B11001_006E).
- `_eval_condition` now warns once per missing field rather than silently scoring all conditions on absent fields as zero.
- Removed dead `_score_normie` code path.
- Conley sandwich and EBLUP synthetic_full no longer emit overflow warnings; non-finite diagonal entries are coerced to 0 prior to sqrt.
- Moran's I PUMA-id mismatch (7-char vs. 5-char) corrected via state-prefix stripping in `build_puma_queen_neighbors`.
- Conley docstring/comment drift: said "reported as NaN" but code returns 0.0 — comment now matches the implementation.

### Removed

- `cowboy` and `filipina_nurse` cohorts (the former had near-zero tract marginal signal; the latter had y_mean of 5.93 from the 1-Year sample which made small-area estimation degenerate).
- `loocv_unreliable` flag — kept the per-λ failed-splits count but removed the binary flag after audit found no canonical academic basis for the threshold.
- PUMA-level outputs (`scores.json`, `pumas_ca.geojson`, `summary.json`) from the web app's required inputs. They are still produced by the pipeline as intermediate artefacts.

## [0.1.0] — 2026-04

Initial cut. PUMA-level choropleth, eight v0.2 cohorts, ACS PUMS 2023 1-Year sample. Synthetic estimation without small-area shrinkage or replicate-weight variance. Stub `SAME_SEX` flag.
