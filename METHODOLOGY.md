# Where Real Californians Live — Methodology

## Overview

This document describes the methodology behind *Where Real Californians Live*: data sources, scoring framework, geographic distribution procedure, visualization approach, and known limitations.

Each named cohort (a "subculture") is operationalized as a weighted vector of conditions over American Community Survey (ACS) variables. The pipeline scores ACS Public Use Microdata Sample (PUMS) records against each vector, weights records by their sampling weight, aggregates to PUMA-level cohort estimates, and distributes those estimates to census tracts via a marginal-weighted small-area-estimation step. The resulting tract-level scores are rendered as dot density on an interactive map.

## Data sources

All data is from the U.S. Census Bureau, free and public.

**American Community Survey Public Use Microdata Sample (ACS PUMS), 2023 1-Year.** The PUMS is a roughly 1% sample of California's population released as anonymized individual records. It carries detailed person-level attributes (age, sex, race, education, occupation, industry, income subtypes, commute mode, language, disability, marital status, military service, school enrollment, etc.) and household-level attributes (tenure, household type, units in structure, year built, lot size, heating fuel, agricultural sales, broadband subscription, vehicles available, etc.) that together support multi-dimensional cohort definitions. Each record carries a Public Use Microdata Area (PUMA) identifier as its lowest geographic resolution. PUMAs are statistical areas of approximately 100,000 people each; California has 281 in the 2020 vintage.

**ACS 5-Year Aggregated Tables, 2023, tract level.** Pre-tabulated cross-tabs at the census tract level (~9,000 in California). The PUMS API does not expose tract identifiers (a Census Bureau disclosure rule), so we use the 5-Year Detailed Tables to access tract-level marginal distributions of single variables (e.g. count of renter-occupied households, count of female same-sex unmarried-partner households, count of mobile homes).

**TIGER/Line shapefiles** for census tract boundaries (CA, 2024 vintage), and the cartographic boundary state file for clipping tracts against California's land area to remove ocean, bay, and lake portions of polygons.

**Census Bureau crosswalk file** mapping 2020 census tracts to 2020 PUMAs. Used to determine which PUMA contains each tract.

The PUMS file is downloaded as bulk CSV from the Census FTP rather than via the Microdata API; the ACS aggregated tables are queried via the Census Data API.

## Subculture model

Each subculture is defined as a configuration record with three components:

1. A **trait vector** of weighted conditions over PUMS variables. Each condition is one of: equals a value, in a set of values, in a numeric range, greater-or-equal-than, less-or-equal-than, in the top Nth percentile of the column, mapped to a NAICS sector, or mapped to an SOC major occupation group. Each condition carries a non-negative weight and may optionally be marked as `required` (a hard gate).

2. A **tract marginal** — a single ACS aggregated-table variable used to distribute the subculture's score across the tracts within each PUMA. The marginal is selected to correlate with the cohort's expected geography (e.g. female same-sex unmarried-partner households as the marginal for a queer cohort; mobile home count for a rural marginal-housing cohort; high-value owner-occupied housing for a wealthy-elder cohort).

3. A **proxy-gap note** documented in the configuration, recording the categorical attributes that the trait vector cannot directly capture (e.g. gender identity, political affiliation, religious affiliation, consumption preferences). These notes are part of the published configuration for methodological transparency.

The full configuration is in `data-pipeline/subcultures.yaml`.

## Modeling constraints

The vectors in this implementation observe the following modeling constraints.

**No race or ethnicity as gates or weights.** Cohorts are defined by behavior, occupation, household structure, language, and circumstance. Race is present in the underlying data but is not used as a filter or scoring weight. Any racial composition observed in the geographic distribution is therefore an emergent finding, not an assumption. A single documented exception applies to one cohort, where non-white identity is incorporated as a soft signal; the exception is recorded in the configuration.

**No geographic gating.** Cohorts are not restricted to specific PUMAs, counties, or regions. Geographic concentration emerges from the demographic, occupational, and behavioral signals.

**No political affiliation as a variable.** Census data does not carry political affiliation. Where a cohort's typical character includes political dimensions, those dimensions are not directly measured; the proxy-gap note records this.

**Hard gates reserved for structurally defining traits.** Most conditions are soft (weighted) signals that contribute fractionally to the score. Hard gates are reserved for variables that structurally define category membership rather than score it.

## Scoring

For each PUMS person record and each subculture, we compute a similarity score in [0, 1] as follows:

1. Evaluate every condition in the subculture's trait vector against the record. Each condition returns 1 if satisfied, 0 if not.
2. If any condition is marked as `required` and returns 0, the record's score for this subculture is 0.
3. Otherwise, compute `score = sum(weight_i * match_i) / sum(weight_i)`. The denominator normalizes to [0, 1].

Records that exactly satisfy the full vector score 1.0; records that satisfy none of the soft conditions (but pass all gates) score 0.

Each record is then weighted by its person weight (`PWGTP`, an integer count of how many real Californians the sampled record represents) and aggregated by PUMA:

```
PUMA_score(subculture) = sum over PUMS records in PUMA of (similarity_score × PWGTP)
```

The result is a weighted population estimate of the subculture's PUMA-level cohort.

**Interpretation.** The PUMA-level score is a weighted population estimate, not a count. Because soft conditions contribute fractional matches, sums of scores across cohorts can exceed the actual population: a single individual may partially match multiple cohort vectors. The score is therefore best treated as a relative concentration measure across PUMAs within a single cohort, not as a head count of cohort membership.

## Geographic distribution (small-area estimation)

PUMS is a PUMA-level dataset. To render the map at higher resolution than 281 large polygons, we redistribute each PUMA's score across the tracts inside it using a tract-level ACS marginal that correlates with the subculture.

For subculture *s* with tract marginal variable *m_s*, and PUMA *p* containing tracts *T(p)*:

```
share(t, s) = m_s(t) / sum over t' in T(p) of m_s(t')
tract_score(t, s) = PUMA_score(p, s) × share(t, s)
```

If the marginal sum within a PUMA is zero (no tract in that PUMA has any of the marginal variable), the score is distributed uniformly across the PUMA's tracts as a fallback.

This is a standard form of small-area estimation: the source distribution is observed at the PUMA level, and the estimate is downscaled to tracts using a covariate that correlates with the target distribution. The estimate inherits whatever bias the chosen marginal carries — for instance, a marginal of female same-sex unmarried-partner households downscales toward tracts with visible lesbian-couple households and under-represents single LGBTQ residents and gay-male-coded enclaves. Each cohort's marginal is documented in the configuration.

Tract-level scores describe how the PUMA-level cohort estimate is distributed across the tracts of that PUMA, conditional on the chosen marginal. They are not direct counts of cohort membership at the tract level.

## Visualization (dot density)

The map renders each tract score as randomly placed dots inside the tract polygon. The number of dots is `floor(tract_score / DOTS_PER_UNIT)` where `DOTS_PER_UNIT` is a tunable constant (currently 150). Random points are generated by rejection sampling within each tract's bounding box, accepted if they lie inside the tract polygon (using a standard ray-casting point-in-polygon test from `@turf/boolean-point-in-polygon`).

The PUMA and tract polygons are pre-clipped against the California state cartographic boundary (the "land" version, which excludes major water bodies). Dots therefore only fall on land.

Multiple subcultures can be rendered simultaneously. Each subculture has its own color; dots from different subcultures stack as separate point features and blend visually.

Dot counts are proportional to the underlying tract-level score within a single fixed dots-per-unit ratio. Smaller cohorts therefore render genuinely fewer dots than larger cohorts; per-cohort dot counts are not normalized for visual comparability.

## Limitations

**Trait vectors are correlate-based, not direct measurements.** Cultural attributes are not directly observable in census data; the vectors describe demographic, occupational, and behavioral correlates. Two cohorts with overlapping correlate profiles will produce similar geographic distributions even if the underlying cultural attributes differ.

**Several attributes are absent from census data.** Gender identity, sexual orientation beyond same-sex household composition, religion, political affiliation, and consumption preferences are not collected by the ACS. Cohorts whose defining attributes fall into these categories rely on correlated proxies; the proxy-gap notes record this per cohort.

**The same-sex household indicator covers only a portion of LGBTQ Californians.** Roughly 20% of LGBTQ adults are in same-sex partnerships at any given time, so cohort definitions that depend on this indicator systematically under-represent single LGBTQ residents.

**Soft scoring produces fractional matches.** Because conditions contribute fractionally to scores, individuals may partially match multiple cohort vectors. Sums of weighted scores across all cohorts therefore can exceed actual population, and absolute scores should not be read as head counts.

**Tract-level estimates inherit marginal bias.** Each cohort's tract-level distribution is only as accurate as the correlation between the chosen marginal and the unobserved true cohort distribution.

**PUMS is a 1% sample.** Sampling weights are used throughout, but cohorts with very few matching records carry larger sampling variance, particularly at fine geographic resolution.

**Cartographic clipping is at 1:500,000 scale.** Coastlines, bay edges, and small water bodies are simplified at this resolution; tract boundaries near these features are approximate.

## Reproducibility

The full pipeline — configuration, scoring code, distribution code, and visualization code — is open. The relevant files are:

- `data-pipeline/subcultures.yaml` — every condition, weight, gate, and marginal for every cohort.
- `data-pipeline/pipeline.py` — fetches PUMS, scores records, distributes to tracts, writes outputs.
- `web/components/MapView.tsx` — rendering.

Modifying a single weight in the configuration, re-running the pipeline (approximately one minute on cached data), and re-rendering produces an updated map. There is no hidden tuning; the methodology is fully expressed in the configuration and code.
