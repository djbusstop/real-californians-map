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

PUMS is a PUMA-level dataset. To render the map at higher resolution than 281 polygons, we apply a synthetic estimator from the Fay-Herriot family (Fay & Herriot 1979), distributing each PUMA-level cohort estimate across its constituent tracts conditional on chosen tract-level covariates. The choice to operate at the area level rather than fit a unit-level model reflects that PUMS records carry no tract identifier (Census disclosure rule), so tract-level direct estimation from microdata is not feasible.

### Step 1 — Fit a non-negative ridge regression per cohort

For each cohort *s*, we collect one or more tract-level ACS marginal variables `M_1(t), M_2(t), …, M_K(t)` declared in the configuration. Tract-level marginals are aggregated to PUMA totals by summing across the tracts of each PUMA. We also fetch tract population from ACS table B01003 and aggregate it to PUMA population.

The design matrix has columns `[pop, M_1, M_2, …, M_K]`, one row per PUMA. All predictors are z-score standardized (mean zero, unit variance) so the L2 ridge penalty applies uniformly across columns of different scales (Hastie, Tibshirani & Friedman 2009, *Elements of Statistical Learning* §3.4). We then fit:

```
PUMA_score(p, s) = ȳ + Σ_k β_k · z_k(p) + ε_p,    β_k ≥ 0
```

with coefficients chosen by ridge regression with non-negativity constraints. The fit minimizes:

```
||y − Xβ||² + λ ||β||²    subject to β ≥ 0
```

solved via the augmented system `[X; √λ I]β = [y; 0]` and Lawson-Hanson NNLS (Lawson & Hanson 1974, *Solving Least Squares Problems*).

Three deliberate methodological choices stand behind this specification:

**Non-negativity constraints (NNLS).** Tract-level predictors are non-negative counts (population, count of housing units of a given type, count of households of a given language), and so is the response (PUMA-level cohort weighted estimate). A negative coefficient would imply a count predictor *suppresses* cohort membership, which is conceptually awkward without a structural justification. NNLS forces the constraint structurally rather than relying on post hoc interpretation.

**Ridge regularization (Hoerl & Kennard 1970).** Tract-level count predictors at PUMA scale are nearly always strongly collinear with PUMA population. Ordinary least squares via SVD silently truncates singular values for collinear columns, which produces coefficients that are zero by numerical accident rather than by data signal. Ridge applies an L2 penalty that distributes weight across correlated predictors instead of zero-truncating, recovering an interpretable coefficient pattern. The penalty parameter λ is selected per cohort by leave-one-PUMA-out cross-validation across the grid `{0, 0.1, 1, 10, 100, 1000, 10000}`.

**Standardization.** Without standardization, the L2 penalty would shrink large-scale predictors (e.g., raw population counts in the hundreds of thousands) less than small-scale predictors (e.g., niche language speaker counts in the thousands), an inadvertent prior on the answer.

### Step 2 — Predict tract scores and rake to PUMA totals

For each tract *t* in PUMA *p*, the model predicts a raw tract count using the standardization parameters fit at PUMA level:

```
predicted(t) = ȳ + Σ_k β_k · ((x_k(t) − μ_k) / σ_k)
```

Negative predictions (which can arise from below-mean predictor values combined with non-negative coefficients in a centered model) are clipped to zero. Within each PUMA, predicted tract counts are then *raked* (proportionally rescaled) so they sum to the PUMS-derived `PUMA_score(p, s)`:

```
tract_score(t, s) = predicted(t) · ( PUMA_score(p, s) / Σ_{t'∈T(p)} predicted(t') )
```

Raking is a benchmarking constraint standard in production small-area estimation (Rao & Molina 2015, *Small Area Estimation*, 2nd ed., Wiley, §6.4). It ensures the tract-level estimates are internally consistent with the PUMA-level direct estimates: the cohort total inside any PUMA never exceeds what PUMS measured, regardless of model error.

### Diagnostics

For each cohort, `data/model_summaries.json` records:

- **Coefficients** in standardized units, with corresponding feature means and standard deviations so predictions can be reconstructed.
- **In-sample R²** and **leave-one-PUMA-out cross-validated R²**. The CV R² is the principled fit metric; in-sample R² is reported alongside for context.
- **Residual standard deviation** in the original cohort-score units.
- **Variance Inflation Factor (VIF)** per predictor (Belsley, Kuh & Welsch 1980, *Regression Diagnostics*, Wiley). VIF > 10 conventionally signals problematic multicollinearity. Values are reported transparently rather than hidden by SVD truncation.
- **Condition number** of the standardized design matrix as a global multicollinearity diagnostic.
- **Global Moran's I on residuals** (Moran 1950) using a queen-contiguity binary spatial weights matrix on the PUMA polygons (Cliff & Ord 1981). The reported z-score and p-value are computed under the normality assumption. A significant Moran's I in residuals indicates the linear model leaves spatial structure unexplained; we discuss this explicitly in the Limitations section rather than absorb it silently.
- **Cross-validation grid** showing LOOCV R² at each candidate λ, so the regularization choice is auditable.

### Fallback: equal-weight share-blend

When the regression cannot fit (fewer than 8 PUMAs with valid data, singular design matrix after standardization, or LOOCV R² below 0.05) the cohort falls back to an equal-weight convex combination of normalized marginal shares within each PUMA:

```
share(t, s) = (1/K) · Σ_k ( M_k(t) / Σ_{t'∈T(p)} M_k(t') )
tract_score(t, s) = PUMA_score(p, s) · share(t, s)
```

This is a closed-form equivalent of Iterative Proportional Fitting (Deming & Stephan 1940) reduced to a single-axis distribution problem. If all marginals are zero across a PUMA, the score is distributed uniformly across the PUMA's tracts. `model_summaries.json` records which method was used per cohort, the rejected regression diagnostics (when relevant), and the fallback reason.

### Interpretation

The estimate inherits whatever bias the chosen marginals collectively carry. Multi-marginal regression mitigates the bias of any single marginal: for instance, a queer-cohort estimate built only from female same-sex partner counts would under-represent gay-male-coded geography, but adding male same-sex partner counts as an additional regressor lets the data adjudicate (where such data is available at tract level — see Limitations). Coefficients, fit stats, and full diagnostics are saved per cohort so this trade-off is auditable.

Tract-level scores describe how the PUMA-level cohort estimate is distributed across the tracts of that PUMA, conditional on the chosen marginals and the fitted relationship. **They are not direct counts of cohort membership at the tract level.** Inference is at the PUMA level; tract-level allocation is descriptive.

## Visualization (dot density)

The map renders each tract score as randomly placed dots inside the tract polygon. The number of dots is `floor(tract_score / DOTS_PER_UNIT)` where `DOTS_PER_UNIT` is a tunable constant (currently 100). Random points are generated by rejection sampling within each tract's bounding box, accepted if they lie inside the tract polygon (using a standard ray-casting point-in-polygon test from `@turf/boolean-point-in-polygon`).

**What one dot represents.** The tract score sums `(similarity × PWGTP)` across PUMS records, then multiplies by the tract share of the marginal. Each unit of the resulting score is therefore approximately one weighted cohort-equivalent person: one full match contributes one unit, two half-matches contribute one unit between them, and so on. With `DOTS_PER_UNIT = 100`, a single dot represents on the order of 100 cohort-equivalent people in that tract. The user-facing legend reads "1 dot ≈ 100 people" with the understanding that "people" here means the weighted-similarity equivalent rather than a discrete headcount.

Across all selected cohorts, the combined dot feature collection is randomly shuffled (Fisher–Yates) before being assigned to the rendering source. This prevents systematic paint-order bias between cohorts: when multiple cohorts are visualised simultaneously, no single cohort's dots are consistently drawn above another's.

The PUMA and tract polygons are pre-clipped against the California state cartographic boundary (the "land" version, which excludes major water bodies). Dots therefore only fall on land.

Multiple subcultures can be rendered simultaneously. Each subculture has its own color; dots from different subcultures stack as separate point features and blend visually.

Dot counts are proportional to the underlying tract-level score within a single fixed dots-per-unit ratio. Smaller cohorts therefore render genuinely fewer dots than larger cohorts; per-cohort dot counts are not normalized for visual comparability.

## Limitations

**Trait vectors are correlate-based, not direct measurements.** Cultural attributes are not directly observable in census data; the vectors describe demographic, occupational, and behavioral correlates. Two cohorts with overlapping correlate profiles will produce similar geographic distributions even if the underlying cultural attributes differ.

**Several attributes are absent from census data.** Gender identity, sexual orientation beyond same-sex household composition, religion, political affiliation, and consumption preferences are not collected by the ACS. Cohorts whose defining attributes fall into these categories rely on correlated proxies; the proxy-gap notes record this per cohort.

**The same-sex household indicator covers only a portion of LGBTQ Californians.** Roughly 20% of LGBTQ adults are in same-sex partnerships at any given time, so cohort definitions that depend on this indicator systematically under-represent single LGBTQ residents.

**Soft scoring produces fractional matches.** Because conditions contribute fractionally to scores, individuals may partially match multiple cohort vectors. Sums of weighted scores across all cohorts therefore can exceed actual population, and absolute scores should not be read as head counts.

**Tract-level estimates inherit marginal bias.** Each cohort's tract-level distribution is only as accurate as the correlation between the chosen marginals and the unobserved true cohort distribution.

**PUMS is a 1% sample.** Sampling weights are used throughout, but cohorts with very few matching records carry larger sampling variance, particularly at fine geographic resolution. The current model is a synthetic estimator and does not explicitly account for the sampling variance of PUMS direct estimates. A full Fay-Herriot specification with replicate-weight variance estimation is documented as a planned methodological improvement.

**Residuals exhibit significant positive spatial autocorrelation.** Across all cohorts where the regression fits, Moran's I on PUMA-level residuals is significantly positive (typically *I* ≈ 0.27–0.42 with *z* > 7, *p* < 10⁻¹⁵ under the normality assumption). This indicates the linear model leaves geographic structure unexplained: cohorts cluster in ways the demographic and housing predictors cannot fully capture. We deliberately retain a non-spatial specification because (a) the unit of inference is the PUMA, not the tract, with tract-level allocation conditional on the PUMA total, and (b) a full spatial regression (SAR or SEM in the sense of Anselin 1988, *Spatial Econometrics*) is beyond the scope of this descriptive cartographic project. We disclose the diagnostic per cohort rather than absorb it. Future work could fit `y = ρWy + Xβ + ε` (LeSage & Pace 2009, *Introduction to Spatial Econometrics*) to address residual spatial dependence.

**Influential-observation diagnostics are not currently reported.** During leave-one-PUMA-out cross-validation, some splits exhibit numerical sensitivity in the augmented NNLS+Ridge solver. The fitted coefficients on the held-in observations remain correct, but the sensitivity itself is a signal that individual PUMAs may exert disproportionate influence on the regression. We do not currently compute per-observation leverage (hat-matrix diagonals) or Cook's distance per cohort. A reviewer interested in robustness to influential observations should treat this as a known gap; standard remedies (Belsley, Kuh & Welsch 1980) would be a natural extension. For California specifically, the PUMAs likely to carry high leverage are those with extreme cohort concentration (Castro / West Hollywood for queer cohorts, the Central Valley Spanish corridor for bilingual_baddie) where the cohort score and the marginal predictors are both far from the cross-PUMA mean.

**Tract-level disclosure suppression in 2023 ACS 5-Year affects some natural marginal choices.** Detailed-language Table B16001 and same-sex partner-household Table B11009 return zero values at tract level despite having non-zero data at PUMA level. We use the collapsed Table C16001 (which loses Punjabi and Armenian as separable categories) and Table B11001 (nonfamily households as a proxy for same-sex household geography). The trait vector still captures the identity signal at the PUMS person-record level; the tract-level marginal is only used for within-PUMA spatial allocation.

**Cartographic clipping is at 1:500,000 scale.** Coastlines, bay edges, and small water bodies are simplified at this resolution; tract boundaries near these features are approximate.

## Reproducibility

The full pipeline — configuration, scoring code, distribution code, and visualization code — is open. The relevant files are:

- `data-pipeline/subcultures.yaml` — every condition, weight, gate, and marginal for every cohort.
- `data-pipeline/pipeline.py` — fetches PUMS, scores records, distributes to tracts, writes outputs.
- `web/components/MapView.tsx` — rendering.

Modifying a single condition in the configuration, re-running the pipeline (approximately one minute on cached data), and re-rendering produces an updated map. There is no hidden tuning; the methodology is fully expressed in the configuration and code.

## References

- Anselin, L. (1988). *Spatial Econometrics: Methods and Models*. Kluwer Academic Publishers.
- Belsley, D. A., Kuh, E., & Welsch, R. E. (1980). *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*. Wiley.
- Cliff, A. D., & Ord, J. K. (1981). *Spatial Processes: Models and Applications*. Pion.
- Deming, W. E., & Stephan, F. F. (1940). On a least squares adjustment of a sampled frequency table when the expected marginal totals are known. *Annals of Mathematical Statistics*, 11(4), 427–444.
- Fay, R. E., & Herriot, R. A. (1979). Estimates of income for small places: An application of James-Stein procedures to census data. *Journal of the American Statistical Association*, 74(366), 269–277.
- Hastie, T., Tibshirani, R., & Friedman, J. (2009). *The Elements of Statistical Learning* (2nd ed.). Springer.
- Hoerl, A. E., & Kennard, R. W. (1970). Ridge regression: Biased estimation for nonorthogonal problems. *Technometrics*, 12(1), 55–67.
- Lawson, C. L., & Hanson, R. J. (1974). *Solving Least Squares Problems*. Prentice-Hall.
- LeSage, J. P., & Pace, R. K. (2009). *Introduction to Spatial Econometrics*. CRC Press.
- Moran, P. A. P. (1950). Notes on continuous stochastic phenomena. *Biometrika*, 37(1/2), 17–23.
- Rao, J. N. K., & Molina, I. (2015). *Small Area Estimation* (2nd ed.). Wiley.
