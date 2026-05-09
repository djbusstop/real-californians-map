# Where Real Californians Live — Methodology

## Overview

"Where Real Californians Live" renders the geographic distribution of named cultural archetypes (the "subcultures") across California census tracts. Each subculture is a deliberately curated, named idea (e.g. "queer leftist", "crumbl cookie couple", "boomers with money") expressed as a vector of weighted census variables. The map shows where in California those vectors statistically concentrate.

The project has two distinct layers: an **editorial layer** that defines what counts as each subculture, and an **analytical layer** that maps that definition onto Census Bureau data. The editorial layer is unapologetically subjective. The analytical layer is reproducible and grounded in standard small-area-estimation techniques.

This document describes the analytical layer in detail and is honest about where the editorial layer makes the analysis approximate rather than rigorous.

## Data sources

All data is from the U.S. Census Bureau, free and public.

**American Community Survey Public Use Microdata Sample (ACS PUMS), 2023 1-Year.** The PUMS is a roughly 1% sample of California's population released as anonymized individual records. It carries detailed person-level attributes (age, sex, race, education, occupation, industry, income subtypes, commute mode, language, disability, marital status, military service, school enrollment, etc.) and household-level attributes (tenure, household type, units in structure, year built, lot size, heating fuel, agricultural sales, broadband subscription, vehicles available, etc.) that together support multi-dimensional cohort definitions. Each record carries a Public Use Microdata Area (PUMA) identifier as its lowest geographic resolution. PUMAs are statistical areas of approximately 100,000 people each; California has 281 in the 2020 vintage.

**ACS 5-Year Aggregated Tables, 2023, tract level.** Pre-tabulated cross-tabs at the census tract level (~9,000 in California). The PUMS API does not expose tract identifiers (a Census Bureau disclosure rule), so we use the 5-Year Detailed Tables to access tract-level marginal distributions of single variables (e.g. count of renter-occupied households, count of female same-sex unmarried-partner households, count of mobile homes).

**TIGER/Line shapefiles** for census tract boundaries (CA, 2024 vintage), and the cartographic boundary state file for clipping tracts against California's land area to remove ocean, bay, and lake portions of polygons.

**Census Bureau crosswalk file** mapping 2020 census tracts to 2020 PUMAs. Used to determine which PUMA contains each tract.

The PUMS file is downloaded as bulk CSV from the Census FTP rather than via the Microdata API; the ACS aggregated tables are queried via the Census Data API.

## Subculture model (the editorial spine)

Each subculture is defined as a YAML record with three core elements:

1. A **trait vector** of weighted conditions over PUMS variables. Each condition is one of: equals a value, in a set of values, in a numeric range, greater-or-equal-than, less-or-equal-than, in the top Nth percentile of the column, mapped to a NAICS sector, or mapped to an SOC major occupation group. Each condition has a weight (typically 0.5 to 4) and may optionally be marked as "required" (a hard gate).

2. A **tract marginal** — a single ACS aggregated-table variable used to distribute that subculture's score across the tracts within each PUMA. The marginal is chosen to correlate with the subculture's expected geography (e.g. female same-sex unmarried-partner households for queer leftist; mobile home count for hill people; $200k+ households for boomers-with-money).

3. A **proxy gap** description, documented in the subculture YAML (not necessarily surfaced in the rendered UI), that records honestly what the trait vector cannot capture. For example: "Census doesn't capture gender identity," "no political affiliation in census," "doesn't measure wine consumption," "thicc is not a census variable." These notes exist for methodological transparency and are part of the published configuration.

The set of subcultures, their names, and the trait weights are all editorial choices. Two analysts working with the same data would produce different subculture libraries. We do not claim the library is canonical or exhaustive.

## Editorial principles

A small set of principles constrain the editorial layer.

**No race or ethnicity as gates or weights.** Subcultures are defined by behavior, occupation, household structure, language, and circumstance. Race is captured in the underlying data but is not used as a filter or scoring weight. Whatever racial composition emerges from the geographic concentrations is a finding, not a definition. A single exception was made for queer leftist, where non-white identity and Hispanic origin are included as soft signals based on user editorial judgment that the queer leftist coalition in California is statistically more diverse than the population at large; this exception is documented in the YAML.

**No geographic gating.** Subcultures are not restricted to specific PUMAs, counties, or regions. Geographic concentration emerges from the demographic, occupational, and behavioral signals.

**No politics as a defining variable.** Census carries no political affiliation. Where a subculture has political flavor (e.g. queer leftist), the politics is inferred from correlated demographic signals and disclosed as a proxy gap.

**Soft scoring is preferred to hard gates** except for traits that structurally define category membership. For example: never-married is a hard gate for "stupid guys" because the archetype is structurally about not having formed a partnership; mobile-home dwelling is a soft signal for "hill people" because the archetype admits cabin and old-farmhouse variants too.

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

**Honest interpretation.** The PUMA score is *not* a count of "how many people are in this subculture." Soft scoring means a record with partial matches contributes a fractional weight. A typical subculture's PUMA scores sum to a population that may exceed the actual population because individuals can partially match multiple subcultures simultaneously. We treat the PUMA score as a relative-concentration signal, comparable across PUMAs within a subculture, but not interchangeable with a head count. The editorial proxy gap descriptions reinforce this for readers.

## Geographic distribution (small-area estimation)

PUMS is a PUMA-level dataset. To render the map at higher resolution than 281 large polygons, we redistribute each PUMA's score across the tracts inside it using a tract-level ACS marginal that correlates with the subculture.

For subculture *s* with tract marginal variable *m_s*, and PUMA *p* containing tracts *T(p)*:

```
share(t, s) = m_s(t) / sum over t' in T(p) of m_s(t')
tract_score(t, s) = PUMA_score(p, s) × share(t, s)
```

If the marginal sum within a PUMA is zero (no tract in that PUMA has any of the marginal variable), the score is distributed uniformly across the PUMA's tracts as a fallback.

This is a standard form of small-area estimation: the source distribution is at the PUMA level, the estimate is downscaled to tracts using a covariate that correlates with the target distribution. The estimate inherits whatever bias the marginal carries. For example, queer leftist uses female same-sex unmarried-partner households as the marginal, which biases toward neighborhoods with visible lesbian couples and may under-represent gay male enclaves and single LGBTQ residents. Each subculture's marginal is documented in the YAML.

The tract scores are *not* claims about how many people live in each tract; they are claims about how the PUMA's modeled cohort distributes within the PUMA, given the marginal.

## Visualization (dot density)

The map renders each tract score as randomly placed dots inside the tract polygon. The number of dots is `floor(tract_score / DOTS_PER_UNIT)` where `DOTS_PER_UNIT` is a tunable constant (currently 150). Random points are generated by rejection sampling within each tract's bounding box, accepted if they lie inside the tract polygon (using a standard ray-casting point-in-polygon test from `@turf/boolean-point-in-polygon`).

The PUMA and tract polygons are pre-clipped against the California state cartographic boundary (the "land" version, which excludes major water bodies). Dots therefore only fall on land.

Multiple subcultures can be rendered simultaneously. Each subculture has its own color; dots from different subcultures stack as separate point features and blend visually.

The dot count is genuinely proportional to the underlying score. Smaller subcultures (queer leftist gated on same-sex household) genuinely render fewer dots than broader subcultures (crumbl cookie couple). We do not normalize per-subculture dot counts to make them visually equivalent.

## Limitations

**Census can't measure culture, only correlates of it.** A trait vector approximates a cultural archetype using demographic, occupational, and behavioral fingerprints. Two different subcultures with overlapping fingerprints will look similar on the map even when they are culturally distinct in life. Per-subculture proxy gaps are recorded in the YAML configuration as part of the methodological record.

**No gender identity, sexual orientation beyond same-sex households, religion, or politics** are in census data. Where a subculture's defining trait is one of these, we use correlated proxies and disclose the gap.

**The same-sex household indicator misses the majority of LGBTQ Californians.** Only roughly 20% of LGBTQ adults are in same-sex partnerships at any given time. The visible queer geography is therefore biased toward partnered queer adults.

**Soft scoring inflates apparent counts.** Sums across subcultures can exceed actual population. The map is honest about relative shape; absolute counts are not directly meaningful.

**Tract-level estimates inherit marginal bias.** A subculture's geographic distribution within each PUMA is only as accurate as its tract marginal correlation with the true cohort.

**PUMS is a sample.** Records carry sampling weights and small populations are noisier than large ones. Subcultures with very few matching records will have noisier geographic estimates.

**The cartographic boundary clip is at 1:500,000 scale.** Coastlines and bay edges are simplified; very fine geographic details may be slightly inaccurate.

**Editorial choices are subjective.** Two analysts choosing different traits, weights, gates, or marginals would produce different maps. The maps are interpretable propositions, not measurements.

## Reproducibility

The full pipeline, including the subculture YAML config, scoring code, distribution code, and visualization code, is open and runnable. Specifically:

- `data-pipeline/subcultures.yaml` — every trait, weight, gate, and marginal for every subculture, fully readable.
- `data-pipeline/pipeline.py` — fetches PUMS, scores records, distributes to tracts, writes outputs.
- `web/components/MapView.tsx` — rendering.

A user can change a single weight in the YAML, re-run the pipeline (about one minute on cached data), re-render the map, and compare. There is no hidden tuning. The methodology is the configuration.

## What this analysis is, and isn't

This analysis is a structured way to ask "where in California do census-visible demographic fingerprints of curated archetypes concentrate?" That question is answerable, transparent, and reproducible.

It is not a count of people, a measurement of culture, or a definitive map of where any community lives. It is a model — and the editorial half of the model is up for argument.
