# Where Real Californians Live — Methodology

## Project framing

*Where Real Californians Live* is a work of speculative cartography rather than spatial demography. It does not claim to objectively measure how cultural groups are distributed across the state. It asks a different question: when a cultural archetype is operationalized as a vector of demographic, occupational, and household characteristics, does the resulting geography match the one that motivated the archetype in the first place?

The trait vector for each cohort is therefore the hypothesis, not the measurement. We are testing whether stereotypes, archetypes, and other intuitive cultural categories have demographic anchoring in census data. Some categories validate cleanly: the bilingual baddie (young, female, non-English at home, service or healthcare-support work, lives with family or roommates, lower-middle income) maps closely onto Spanish-language and Hispanic-population geography in California. Other categories anchor poorly. Married gays exist in a handful of historical enclaves (the Castro, West Hollywood, Palm Springs) rather than as a smooth demographic gradient, so the cohort's regression R² is low and residual Moran's I is small. This is not because the model is broken; it is because the category lives in cultural-historical specificity that demographic predictors cannot reach.

Both outcomes are findings. A cohort that maps tightly tells us its archetype is demographically real, in the sense that the census measures it. A cohort that maps loosely tells us its archetype lives more in cultural performance, historical migration patterns, or other non-demographic anchorings. The map is the medium of the test, and the test sits in the third position between "stereotypes are obviously true" and "stereotypes are obviously made up." It says: here is whether your imagination of a cultural category has demographic anchoring, given the census's particular categories.

Methodological precedents for this orientation include Rebecca Solnit's *Infinite City: A San Francisco Atlas* (University of California Press, 2010) and the broader tradition of speculative or critical cartography, which treats geographic data as a substrate for rendering social imaginaries rather than for measuring objective truths. The statistical rigor of this project (Fay-Herriot area-level estimation, ridge regression with non-negativity constraints, leave-one-out cross-validation, Conley spatial HAC standard errors, non-parametric bootstrap percentile intervals, Moran's I residual diagnostics, VIF reporting) is what makes each observation within each test reliable. The tests themselves, however, are intentionally subjective: they operationalize cultural intuition into census categories and report what the data does with them. The "Sources of uncertainty" subsection of Limitations names the irreducibly subjective component of the project explicitly.

## Overview

This document describes the methodology behind *Where Real Californians Live*: data sources, scoring framework, geographic distribution procedure, visualization approach, and known limitations.

Each named cohort (a "subculture") is operationalized as a weighted vector of conditions over American Community Survey (ACS) variables paired with a per-cohort membership threshold τ. The pipeline scores ACS Public Use Microdata Sample (PUMS) records against each vector, applies the threshold to derive a binary cohort membership indicator per record, weights records by their sampling weight, aggregates to PUMA-level cohort member counts, and distributes those counts to census tracts via a marginal-weighted small-area-estimation step. The resulting tract-level member counts are rendered as dot density on an interactive map.

## Data sources

All data is from the U.S. Census Bureau, free and public.

**American Community Survey Public Use Microdata Sample (ACS PUMS), 2023 5-Year (covering 2019–2023).** The PUMS is an anonymized individual-record release of about 5% of California's population pooled across the five survey years (~2 million CA person records and ~830k housing-unit records). It carries detailed person-level attributes (age, sex, race, education, occupation, industry, income subtypes, commute mode, language, disability, marital status, military service, school enrollment, etc.) and household-level attributes (tenure, household type, units in structure, year built, lot size, heating fuel, agricultural sales, broadband subscription, vehicles available, etc.) that together support multi-dimensional cohort definitions. Each record carries a Public Use Microdata Area (PUMA) identifier as its lowest geographic resolution. PUMAs are statistical areas of approximately 100,000 people each; California has 281 in the 2020 vintage.

The 5-year file is preferred over the 1-year file at this scale because narrow trait vectors (e.g., gated on `SAME_SEX = 1` or `INDP = agriculture`) produce small per-PUMA cohorts whose direct estimates carry high sampling variance under a single year of data. With ~5× more records, per-PUMA σ²_e drops by roughly the same factor, the Fay-Herriot EBLUP shrinkage retreats toward the direct estimates, and coefficient bootstrap confidence intervals tighten. The trade-off is that 5-year estimates are an average over 2019–2023 rather than a 2023-only snapshot — appropriate for the structural questions this project asks, less so for tracking sharp recent inflections (e.g., post-COVID work-from-home shifts).

**ACS 5-Year Aggregated Tables, 2023, tract level.** Pre-tabulated cross-tabs at the census tract level (~9,000 in California). The PUMS API does not expose tract identifiers (a Census Bureau disclosure rule), so we use the 5-Year Detailed Tables to access tract-level marginal distributions of single variables (e.g. count of renter-occupied households, count of female same-sex unmarried-partner households, count of mobile homes).

**TIGER/Line shapefiles** for census tract boundaries (CA, 2024 vintage), and the cartographic boundary state file for clipping tracts against California's land area to remove ocean, bay, and lake portions of polygons.

**Census Bureau crosswalk file** mapping 2020 census tracts to 2020 PUMAs. Used to determine which PUMA contains each tract.

The PUMS file is downloaded as bulk CSV from the Census FTP rather than via the Microdata API; the ACS aggregated tables are queried via the Census Data API.

## Subculture model

Each subculture is defined as a configuration record with four components:

1. A **trait vector** of weighted conditions over PUMS variables. Each condition is one of: equals a value, in a set of values, in a numeric range, greater-or-equal-than, less-or-equal-than, in the top Nth percentile of the column, mapped to a NAICS sector, or mapped to an SOC major occupation group. Each condition carries a non-negative weight and may optionally be marked as `required` (a hard gate).

2. A **membership threshold** τ ∈ (0, 1], the cutoff applied to the soft fit score to derive a binary cohort membership indicator. A record counts as a cohort member iff every required condition passes AND the fit score is at or above τ. The default τ is 0.5, declared in the YAML `settings` block; cohorts may override per cohort. The threshold is the place where editorial intent about "how exclusive is this cohort" is concentrated.

3. A **tract marginal** (single ACS aggregated-table variable, or a small set) used to distribute the subculture's PUMA-level member count across the tracts within each PUMA. Marginals are selected to correlate with the cohort's expected geography (e.g. female same-sex unmarried-partner households as the marginal for a queer cohort; mobile home count for a rural marginal-housing cohort; high-value owner-occupied housing for a wealthy-elder cohort).

4. A **proxy-gap note** documented in the configuration, recording the categorical attributes that the trait vector cannot directly capture (e.g. gender identity, political affiliation, religious affiliation, consumption preferences). These notes are part of the published configuration for methodological transparency.

The full configuration is in `data-pipeline/subcultures.yaml`.

### Cohorts in this implementation

Six named cohorts are configured at the time of writing. The expected diagnostic pattern (per the "Diagnostics as calibration signals" subsection below) is noted alongside each.

- **Queer leftist** (`queer_leftist`). College-educated, urban, transit-using, creative-or-social-service occupation, often a student. SAME_SEX = 1 is a heavy soft signal but not a gate, so the cohort spans both partnered and single LGBTQ records plus lifestyle-aligned allies. τ = 0.45. *Demographically anchored* — R² ≈ 0.67, Moran's I residual non-significant.
- **Married gays** (`married_gays`). Any same-sex married couple. *Historically clustered* — R² ≈ 0.20, the cohort lives in a few enclaves (Castro / West Hollywood / Palm Springs) that demographic predictors cannot smoothly map.
- **Bilingual baddie** (`bilingual_baddie`). Young, female, non-English at home, service or healthcare-support work, mid-low income. *Demographically anchored* — R² ≈ 0.82, the highest in the project. The Spanish-language and Hispanic-population marginals carry strong tract-level signal.
- **Crumbl cookie couple** (`crumbl_cookie_couple`). 24-38, married, dual-earner ≥ $130k household income, full-time worker, recent mover, single-family detached or attached, two cars. Both homeowners-with-mortgage and renters qualify (homeowners weighted higher). *Demographically anchored, residual spatial structure remains* — R² ≈ 0.47, Moran's I residual is significant, indicating the new-suburb geography is not fully captured by the chosen marginals.
- **California hillbilly** (`hill_people`). Adult, lives on 1+ acres, mobile home or detached single-family, off-grid heating fuel (wood, propane), low income, often disabled, settled. *Historically clustered* — R² ≈ 0.77 with significant residual Moran's I; concentrates in the Sierra foothills, North Coast, and northeastern California.
- **Crazy person on the bus** (`crazy_person`). Below poverty line (gated), severely mentally-ill (DREM heavy), 25-55, often in shelters or group quarters, no plumbing, long-detached from labor force. *Demographically anchored* — R² ≈ 0.61, concentrating in inner-city tracts (Tenderloin, Skid Row, downtown Oakland) and working-class non-major cities (Stockton, Fresno, Bakersfield).

## Modeling constraints

The vectors in this implementation observe the following modeling constraints.

**No race or ethnicity as gates or weights.** Cohorts are defined by behavior, occupation, household structure, language, and circumstance. Race is present in the underlying data but is not used as a filter or scoring weight. Any racial composition observed in the geographic distribution is therefore an emergent finding, not an assumption. A single documented exception applies to one cohort, where non-white identity is incorporated as a soft signal; the exception is recorded in the configuration.

**No geographic gating.** Cohorts are not restricted to specific PUMAs, counties, or regions. Geographic concentration emerges from the demographic, occupational, and behavioral signals.

**No political affiliation as a variable.** Census data does not carry political affiliation. Where a cohort's typical character includes political dimensions, those dimensions are not directly measured; the proxy-gap note records this.

**Hard gates reserved for structurally defining traits.** Most conditions are soft (weighted) signals that contribute fractionally to the score. Hard gates are reserved for variables that structurally define category membership rather than score it.

## Scoring

The membership rule is two-stage. We first compute a continuous fit score per record, then apply a per-cohort threshold to derive a binary cohort membership indicator. The PUMA-level estimand is then the weighted count of cohort members, a well-defined population total in the standard small-area-estimation sense (Fay & Herriot 1979; Rao & Molina 2015).

Threshold-based membership produces a quantity the downstream Fay-Herriot machinery is designed for: a population total in the standard small-area-estimation sense. The approach connects directly to standard practice in synthetic-population microsimulation, where binary cohort criteria are applied to a tract-resolution synthetic dataset (Beckman, Baggerly & McKay 1996; Williamson, Birkin & Rees 1998; Tanton & Edwards 2013). The threshold-as-operating-point structure is also identical to operating-point selection on a continuous decision function in classifier evaluation (Hanley & McNeil 1982; Pepe 2003).

### Stage 1: Fit score

For each PUMS person record and each subculture, we compute a continuous fit score in [0, 1] as follows:

1. Evaluate every condition in the subculture's trait vector against the record. Each condition returns 1 if satisfied, 0 if not.
2. If any condition is marked as `required` and returns 0, the record's fit score is 0 (the gate fails closed).
3. Otherwise the fit score is `Σ_i weight_i × match_i / Σ_i weight_i`, the weight-normalized fraction of the cohort vector matched by the record.

Records that exactly satisfy the full vector score 1.0. Records that pass all gates but match none of the soft conditions score the gate-only baseline (the fraction of total vector weight contributed by required conditions).

### Stage 2: Membership indicator

Each cohort declares a threshold τ ∈ (0, 1] (default 0.5, settable in the YAML `settings` block, overridable per cohort). A record counts as a cohort member iff (a) its gate evaluates True AND (b) its fit score is at or above τ:

```
member(record, s) = 1   if   gate(record, s)   AND   fit_score(record, s) ≥ τ_s
                  = 0   otherwise
```

The threshold operationalizes "how exclusive is this cohort." A cohort with τ = 0.3 admits records that capture roughly a third of the trait-vector weight; a cohort with τ = 0.7 admits only records that match most of the vector. Where external benchmarks exist (Williams Institute LGBTQ population estimates, Pew language statistics, county voter-registration totals), τ can be calibrated against them; otherwise τ is chosen editorially with stated rationale.

The threshold-based formulation is structurally identical to the operating-point selection problem in classifier evaluation (Hanley & McNeil 1982; Pepe 2003), with τ as the operating point on a continuous decision function.

### Stage 3: PUMA aggregation

Each member indicator is weighted by the record's person weight (`PWGTP`, the integer count of real Californians the sampled record represents) and summed by PUMA:

```
y_p(s) = Σ_{records ∈ p}  member(record, s) × PWGTP(record)
```

The result is a well-defined population total: the weighted count of cohort members in PUMA p. This is the primary estimand fed into the downstream Fay-Herriot small-area estimation pipeline.

### Secondary diagnostics

Three within-cohort diagnostics are retained alongside the primary count, for transparency and threshold-sensitivity analysis. Each is reported per cohort in `summary.json` and `model_summaries.json`.

- **Weighted gate-pass count:** `Σ gate × PWGTP`, the weighted count of records that pass the cohort's required conditions before the threshold filter is applied. The ratio `member_count / gate_pass_count` is the share of gate-passers who clear the threshold; values close to 1 indicate τ is loose, values close to 0 indicate τ is tight.
- **Weighted soft total:** `Σ fit_score × PWGTP`, the weighted sum of fit scores across all gate-passing records. A continuous companion to the binary member count, useful for threshold-sensitivity analysis: it answers "what would the cohort size look like if we credited partial fit instead of binary membership?"
- **Mean fit per member:** `Σ (fit × member × PWGTP) / Σ (member × PWGTP)`, the average fit score among cohort members. Values close to 1 indicate the cohort is dominated by textbook examples; values close to τ indicate the cohort is dominated by marginal qualifiers, which is a sign τ may be too low for the cohort's editorial intent.

### Interpretation

`y_p(s)` is a weighted population total under the threshold-based membership rule. It is interpretable as "the weighted count of California residents in PUMA p who, according to the cohort's editorial vector and threshold, qualify as cohort members." Sums across cohorts can still exceed the state population because cohorts are not mutually exclusive; a single individual may qualify for multiple cohorts. But within a single cohort, `y_p(s)` is a count, not a fuzzy quantity, and the Fay-Herriot, SDR, raking, and external-validation machinery operates on it as a population total in the standard sense.

## Geographic distribution (small-area estimation)

PUMS is a PUMA-level dataset. To render the map at higher resolution than 281 polygons, we apply a Fay-Herriot area-level model (Fay & Herriot 1979) with EBLUP shrinkage, distributing each PUMA-level cohort estimate across its constituent tracts conditional on chosen tract-level covariates. The choice to operate at the area level rather than fit a unit-level model reflects that PUMS records carry no tract identifier (Census disclosure rule), so tract-level direct estimation from microdata is not feasible.

The procedure has three estimation steps: (1) a non-negative ridge regression that produces a synthetic predictor, (2) a Fay-Herriot variance estimation step that combines the synthetic predictor with the direct PUMS estimate via EBLUP shrinkage, and (3) tract-level allocation via raking to the EBLUP totals. Inference on the regression coefficients uses two complementary methods: Conley spatial HAC standard errors and non-parametric bootstrap percentile confidence intervals.

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

### Step 2 — Estimate sampling variance via successive-difference replication (SDR)

The PUMS file ships with 80 successive-difference replicate weights (`PWGTP1`..`PWGTP80`) constructed by the Census Bureau for variance estimation. For each cohort and each PUMA, we compute the cohort score 81 times: once using the main weight `PWGTP`, and once each using `PWGTPr` for *r* = 1..80. The sampling variance of the PUMA-level cohort estimate follows the Census-published formula (Wolter 2007, *Introduction to Variance Estimation*, 2nd ed., Springer, §3.7; Census Bureau, *PUMS Accuracy of the Data* 2023):

```
Var(score_p) = (4/80) · Σ_r (score_p,r − score_p)²
```

These per-PUMA sampling variances σ²_e_p enter the next step as known quantities, distinguishing this from a pure synthetic estimator.

### Step 3 — Fay-Herriot EBLUP shrinkage

The Fay-Herriot area-level model is

```
y_p = X_p β + u_p + e_p,    e_p ~ N(0, σ²_e_p),   u_p ~ N(0, σ²_u)
```

where `y_p` is the PUMA-level direct estimate, `X_p β` is the synthetic predictor from the ridge regression, `e_p` is sampling error with known variance σ²_e_p (from Step 2), and `u_p` is a between-area random effect with unknown variance σ²_u.

We estimate σ²_u via the Prasad-Rao method-of-moments estimator (Prasad & Rao 1990, *JASA* 85(409), 163–171):

```
σ̂²_u = max(0, (1 / (m − p)) · [Σ_p (y_p − X_p β̂)² − Σ_p σ²_e_p])
```

where *m* is the number of PUMAs and *p* is the number of regression parameters. The Empirical Best Linear Unbiased Predictor (EBLUP) for each PUMA is then a weighted combination of the direct estimate and the synthetic predictor:

```
ŷ_FH_p = X_p β̂ + γ_p · (y_p − X_p β̂),    γ_p = σ̂²_u / (σ̂²_u + σ²_e_p)
```

The shrinkage factor γ_p has a clear interpretation: when σ²_e_p is large relative to σ̂²_u (i.e., the PUMS direct estimate for this PUMA has high sampling variance, typically because few records matched the cohort), γ_p is small and the EBLUP shrinks toward the regression prediction. When σ²_e_p is small, γ_p approaches one and the direct estimate is preserved. This is the canonical small-area-estimation tradeoff between synthetic bias and direct-estimate variance.

### Step 4 — Predict tract scores and rake to EBLUP totals

The within-PUMA distribution uses the regression coefficients as a *synthetic share*: the standardized coefficients are back-transformed to raw units (β_raw_k = β̂_k / σ_k), and a tract's relative share within its PUMA is

```
share(t) = Σ_k β_raw_k · x_k(t) = Σ_k (β̂_k / σ_k) · x_k(t)
```

with negative values clipped to zero. Tract scores are then raked within each PUMA so they sum to the EBLUP `ŷ_FH_p`:

```
tract_score(t, s) = share(t) · ( ŷ_FH_p / Σ_{t'∈T(p)} share(t') )
```

This is the synthetic-share form of small-area distribution. The standardized fit at PUMA level (`y_p = α + Σ β̂_k z_k(p)`) is back-transformed to give per-feature unstandardized coefficients β_raw_k = β̂_k / σ_k that apply at any scale; each tract's share is then a non-negative linear combination of its marginal densities. The PUMA-level intercept α (and the y_mean baseline implied by it) does not appear in the within-PUMA share calculation, because it cancels across tracts in the same PUMA and is correctly absorbed by the raking step. A tract with zero on every marginal therefore receives exactly zero allocation, which is the correct behaviour for cohorts whose target geography is sharply rural or sharply urban.

The synthetic-estimator approach has direct precedent in the small-area-estimation literature: Gonzalez (1973) introduced the synthetic estimator using raw covariate coefficients applied at smaller-area scale; Battese, Harter & Fuller (1988) is the canonical paper using unstandardized covariate coefficients to predict county-level crop areas from a satellite-derived synthetic regression; Rao & Molina (2015), *Small Area Estimation*, 2nd ed., Wiley, §4.2 surveys the synthetic and structure-preserving estimator family. The microsimulation literature already cited above for the threshold-membership rule (Williamson, Birkin & Rees 1998; Tanton & Edwards 2013) uses the same synthetic-share logic for tract-resolution allocation. The use of standardized coefficients for fitting and back-transformation for prediction is the standard ridge-regression pattern (Hastie, Tibshirani & Friedman 2009, *Elements of Statistical Learning*, §3.4).

Raking is a benchmarking constraint standard in production small-area estimation (Rao & Molina 2015, §6.4). Using the EBLUP as the raking target rather than the direct estimate is what propagates the sampling-variance correction down to the tract level: noisy PUMS estimates for small-cohort PUMAs are stabilized toward the regression line before being distributed across tracts.

### Diagnostics

For each cohort, `data/model_summaries.json` records:

- **Coefficients** in standardized units, with corresponding feature means and standard deviations so predictions can be reconstructed.
- **In-sample R²** and **leave-one-PUMA-out cross-validated R²**. The CV R² is the principled fit metric; in-sample R² is reported alongside for context. Each leave-one-out fit can fail when the constrained NNLS+Ridge solver returns no valid coefficient vector for that split (typically because the held-in design matrix is rank-deficient or numerically ill-conditioned). The standard convention in cross-validation software (e.g., scikit-learn's `cross_val_score`) is to skip failed folds; this implementation instead substitutes the unconditional mean `y_mean` as the held-out prediction for those splits. The y_mean substitution is a non-standard fallback that conflates "the model failed to fit" with "the model predicts the mean" in the LOOCV residual sum, so the reported LOOCV R² for cohorts with many failed splits should be read as a mixture of regression and null-model performance rather than as a clean estimate of out-of-sample predictive accuracy. The pipeline exposes the count of failed splits per λ (`lambda_cv_failed`) and the count at the chosen λ (`loocv_failed_splits`) as engineering diagnostics so a reviewer can see how much of the LOOCV calculation is the solver-failure fallback. A LOOCV-with-skipped-folds calculation, conditional on successful splits, would be the textbook-correct alternative; the current implementation prioritized auditability of solver behavior over conditional CV.
- **Residual standard deviation** in the original cohort-score units.
- **Variance Inflation Factor (VIF)** per predictor (Belsley, Kuh & Welsch 1980, *Regression Diagnostics*, Wiley). VIF > 10 conventionally signals problematic multicollinearity. Values are reported transparently rather than hidden by SVD truncation.
- **Condition number** of the standardized design matrix as a global multicollinearity diagnostic.
- **Global Moran's I on residuals** (Moran 1950) using a queen-contiguity binary spatial weights matrix on the PUMA polygons (Cliff & Ord 1981). The reported z-score and p-value are computed under the normality assumption. A significant Moran's I in residuals indicates the linear model leaves spatial structure unexplained; we discuss this explicitly in the Limitations section rather than absorb it silently.
- **Cross-validation grid** showing LOOCV R² at each candidate λ, so the regularization choice is auditable.
- **Fay-Herriot variance components** per cohort: the estimated random-effect variance σ̂²_u, the mean sampling variance σ²_e across PUMAs, and the median, minimum, and maximum shrinkage factor γ. Together these summarize how aggressively the cohort's PUMA-level estimates are shrunk toward the regression line.
- **Conley spatial HAC standard errors** (Conley 1999, *Journal of Econometrics* 92, 1-45). A spatially-aware analog of Newey-West HAC, computed as
  ```
  V = (X′X + λI)⁻¹ · X′ Ω X · (X′X + λI)⁻¹,    Ω_ij = K(d_ij / h) · ε_i ε_j
  ```
  where d_ij is the great-circle distance between PUMA centroids in kilometers, K is a Bartlett kernel, h = 75 km is a fixed bandwidth chosen as a moderate cluster size for California's PUMA layout (a few PUMAs in dense urban regions, a single PUMA covering broad rural counties), and the (X′X + λI)⁻¹ form is the ridge-adjusted analog of the OLS sandwich. The reported standard error per coefficient is the square root of the corresponding diagonal element of V. Conley SEs are valid under heteroscedastic, spatially-dependent residuals — exactly the situation our Moran's I diagnostics confirm we have. We do not implement automatic bandwidth selection (Bester, Conley & Hansen 2011, *Journal of Econometrics* 165(2), 137–151; Müller & Watson 2017, *Econometrica* 85(4), 1057–1099). The deliberate choice: this project's primary inference statement on coefficients is the non-parametric bootstrap percentile CI (described next), which is bandwidth-free and respects the soft-scoring fractional-match structure of the cohort definitions. Conley SEs serve as a parametric companion estimate; when the two agree the inferential claim is strengthened, when they disagree the bootstrap is treated as authoritative. Tightening Conley via adaptive bandwidth selection would polish the secondary diagnostic without changing the primary inference.
- **Non-parametric bootstrap percentile confidence intervals** for each coefficient (Efron & Tibshirani 1993, *An Introduction to the Bootstrap*, Chapman & Hall, §13). PUMAs are resampled with replacement 1000 times; at each resample we refit the NNLS+Ridge regression at the LOOCV-selected λ and record the coefficient vector. The 95% CI is the (2.5%, 97.5%) percentile of the empirical distribution. The bootstrap correctly handles both the non-negativity constraint and the ridge regularization, which the Conley estimator handles only approximately. Two complementary inference statements are reported per coefficient: the spatially-aware Conley SE and the non-parametric bootstrap CI; agreement between the two strengthens the inferential claim, disagreement is itself informative. Note that λ is held fixed at the LOOCV-selected value rather than retuned per resample, a "post-selection bootstrap" that ignores λ-selection uncertainty (Hastie, Tibshirani & Friedman 2009, *Elements of Statistical Learning* §7.10.2).

### Diagnostics as calibration signals for the operationalization

A point worth naming explicitly, since it is central to how this project uses its diagnostics. The metrics described above (R², LOOCV R², VIF, condition number, Moran's I, FH variance components, Conley SE, bootstrap CI) are not only checks on the regression's statistical properties. They also serve as evidence about whether the cohort has been operationalized well — but the interpretation depends on the archetype's expected geographic shape, and the same numerical value can be evidence in opposite directions for different cohorts.

Three distinct patterns of "well-operationalized" coexist in this project, and the diagnostics look different in each.

**Broadly-distributed archetypes.** Some cultural categories describe a substantial fraction of the population whose geography maps roughly to total population — common archetypes that are not concentrated in any specific neighborhood type. R² will be high because PUMA population alone predicts the cohort well. Moran's I residual will be small because there is no concentrated spatial pattern left to explain. This is a finding, not a fit failure: the archetype is genuinely common and demographically diffuse, and the model is correctly capturing that. A "broadly distributed" outcome here is the right answer.

**Demographically-anchored archetypes.** Some archetypes track specific census variables sharply — language spoken at home, occupation category, household structure, housing-unit type. When the right marginals are added, R² rises and Moran's I residual falls together. The covariates are explaining both the cohort's size and its spatial pattern. This is the case where iterating on marginal selection visibly improves the operationalization. Three diagnostics moving together signal progress:

1. **R² rises** as the chosen marginals capture variance in the PUMS-derived PUMA estimates.
2. **LOOCV R² rises with R²**, indicating the gain is generalizable rather than overfitting.
3. **Moran's I residual falls** as the marginals soak up previously-residual geographic structure.

**Historically-clustered archetypes.** Some archetypes live in cultural-historical patterns that demographic predictors cannot reach — neighborhoods shaped by specific migration waves, enclaves established decades ago and persisting through cultural memory rather than current demographic mix. R² may be moderate even with careful marginal selection. Moran's I residual may stay significantly positive because the spatial structure is encoded in history rather than in present-day counts. This is also a finding about the archetype: that it lives in cultural-historical specificity rather than in demographic position.

Each pattern is a different way of being operationalized correctly. The numerical diagnostics should be read in conversation with the archetype's editorial intent rather than as standalone pass-fail tests. A high residual Moran's I is a problem when the archetype is supposed to be broadly distributed (suggesting marginal under-specification) and a finding when the archetype is supposed to be culturally clustered (suggesting historical specificity beyond what demographics reach). A low R² is a problem when the cohort is supposed to be concentrated and predictable, and acceptable when the cohort is sparsely sampled or genuinely diffuse. A high R² with low Moran's I is well-fit for both broadly distributed and demographically anchored archetypes, but means something different in each — for the former, "the archetype is everywhere because the population is everywhere"; for the latter, "the chosen marginals are doing real work."

This is consistent with the project's epistemic posture (see "Project framing" above): the diagnostics test a hypothesis about how the archetype meets the data. The hypothesis can succeed or fail in different ways depending on the archetype's underlying geographic shape, and a failed test is itself a finding about the archetype, not only about the model.

#### Precision and what diagnostics can detect

A practical observation worth naming: the same diagnostic value can carry different evidential weight at different signal-to-noise ratios, because residuals are a sum of measurement noise (sampling variance σ²_e) and unexplained structure. When σ²_e is large, residuals are dominated by noise and any underlying spatial pattern in the cohort's geography is *masked* — Moran's I picks up only the small fraction of residual variance that is genuinely structural. When σ²_e drops (e.g., by switching from 1-year to 5-year ACS PUMS, or by including more replicate-weighted records in the SDR variance estimate), the noise floor falls and previously-masked spatial structure becomes measurable.

In practice, this means a Moran's I residual that is statistically non-significant under high-variance estimation can become significant under lower-variance estimation, *without any change to the model's specification*. The cohort's underlying geographic clustering was always there; the diagnostic could not see through the measurement noise to detect it. A jump in residual Moran's I after improving estimation precision is therefore not a sign the model got worse — it is a sign that the diagnostic is now seeing the archetype's real spatial structure rather than its noise-blurred image.

The corollary applies to coefficient inference: bootstrap CIs and Conley SEs both narrow as σ²_e drops, because the sampling distribution of each coefficient becomes tighter. Coefficients that were on the edge of statistical significance under high-variance estimation can become unambiguously bounded under lower-variance estimation. Both improvements reflect the same underlying mechanism: more precise estimates let the diagnostics distinguish signal from noise more cleanly.

### Data-quality guards

The pipeline includes two guards that surface data-quality issues at the source rather than letting them propagate silently into the cohort scores:

**Tract-marginal all-zeros detection.** When `fetch_acs_tract_marginal` retrieves an ACS Detailed Tables variable and the response is 100% zeros across all California tracts, the pipeline prints a warning and refuses to cache the result. The Census Bureau suppresses some detailed tables (e.g., `B16001` detailed-language and `B11009` same-sex partner-household) at tract level for disclosure reasons. Without the guard, an all-zeros response would be cached indefinitely and silently drive the corresponding cohort's tract distribution to a uniform-within-PUMA fallback. With the guard, the configurer is informed that a chosen marginal does not publish at tract level and should be substituted (typically with a collapsed published table such as `C16001`).

**Missing-field detection in trait vectors.** When a condition in `subcultures.yaml` references a PUMS field that is not present in the loaded DataFrame (e.g., a typo such as `AGEPP` for `AGEP`, or a variable that was removed from `PERSON_VARS`), the pipeline prints a one-time warning per field and continues with that condition scoring zero for every record. Without the guard, the cohort would silently lose that condition's contribution and the configurer would have no signal that anything was wrong.

### Numerical robustness

For tightly-gated cohorts where many records score zero (typical of small-sample cohorts under hard gates such as SAME_SEX = 1 or INDP = 11), some intermediate matrix operations in the EBLUP and Conley HAC sandwich computations can produce non-finite values (overflow, NaN, divide-by-zero). The pipeline intercepts these before they reach the output:

- **EBLUP predictions** that are NaN or ±∞ are clipped to zero. The EBLUP is a weighted combination ŷ_FH_p = X_p β̂ + γ_p · (y_p − X_p β̂); when X_p β̂ overflows because of extreme standardized inputs, the affected PUMA's prediction is set to zero rather than propagated forward into the raking step.
- **Conley standard errors** whose corresponding sandwich-variance diagonal element is non-finite are reported as 0.0 rather than NaN. The bootstrap percentile CI is the rigorous companion inference statement in these degenerate cases — when Conley breaks down numerically, bootstrap typically still produces a usable interval.

These guards are documented per cohort: any cohort whose Conley SE column contains exact zeros across all coefficients should be interpreted by the bootstrap CI alone. The numerical-overflow warnings that would otherwise reach the console are suppressed via `numpy.errstate` because their underlying causes are absorbed by these guards; the methodology's reported numbers remain correct.

### Fallback: equal-weight share-blend

When the regression cannot fit (fewer than 8 PUMAs with valid data, singular design matrix after standardization, or LOOCV R² below 0.05) the cohort falls back to an equal-weight convex combination of normalized marginal shares within each PUMA:

```
share(t, s) = (1/K) · Σ_k ( M_k(t) / Σ_{t'∈T(p)} M_k(t') )
tract_score(t, s) = PUMA_score(p, s) · share(t, s)
```

This is a closed-form equivalent of Iterative Proportional Fitting (Deming & Stephan 1940) reduced to a single-axis distribution problem. If all marginals are zero across a PUMA, the score is distributed uniformly across the PUMA's tracts. `model_summaries.json` records which method was used per cohort, the rejected regression diagnostics (when relevant), and the fallback reason.

### Interpretation

The estimate inherits whatever bias the chosen marginals collectively carry. Multi-marginal regression mitigates the bias of any single marginal: for instance, a queer-cohort estimate built only from female same-sex partner counts would under-represent gay-male-coded geography, but adding male same-sex partner counts as an additional regressor lets the data adjudicate (where such data is available at tract level — see Limitations). Coefficients, fit stats, and full diagnostics are saved per cohort so this trade-off is auditable.

Tract-level estimates describe how the PUMA-level cohort *member count* is distributed across the tracts of that PUMA, conditional on the chosen marginals and the fitted relationship. The PUMA-level total is a properly inferred population total under SDR variance accounting and FH shrinkage. The within-PUMA tract allocation is descriptive: it is conditional on the chosen marginals and the regression fit, not a direct estimate from microdata, since PUMS records carry no tract identifier.

## Visualization (dot density)

The map renders each tract score as randomly placed dots inside the tract polygon. The number of dots is `floor(tract_score / DOTS_PER_UNIT)` where `DOTS_PER_UNIT` is a tunable constant (currently 20). Random points are generated by rejection sampling within each tract's bounding box, accepted if they lie inside the tract polygon (using a standard ray-casting point-in-polygon test from `@turf/boolean-point-in-polygon`).

**What one dot represents.** Under the threshold-based membership rule, the PUMA-level estimate `y_p(s)` is `Σ (member × PWGTP)` across PUMS records, the weighted count of cohort members in PUMA p. The tract-level estimate is the within-PUMA share of that count distributed to each tract by the regression-and-raking step. Each unit of the resulting tract estimate therefore corresponds to approximately one cohort member. With `DOTS_PER_UNIT = 20`, a single dot represents on the order of 20 cohort members in that tract. The user-facing legend reads "1 dot ≈ 20 people" and the dot count maps to a meaningful population quantity rather than a fuzzy-set cardinality. The constant is exposed in `web/components/MapView.tsx` and is the only place dot density needs to be edited.

Across all selected cohorts, the combined dot feature collection is randomly shuffled (Fisher–Yates) before being assigned to the rendering source. This prevents systematic paint-order bias between cohorts: when multiple cohorts are visualised simultaneously, no single cohort's dots are consistently drawn above another's.

The PUMA and tract polygons are pre-clipped against the California state cartographic boundary (the "land" version, which excludes major water bodies). Dots therefore only fall on land.

Multiple subcultures can be rendered simultaneously. Each subculture has its own color; dots from different subcultures stack as separate point features and blend visually.

Dot counts are proportional to the underlying tract-level score within a single fixed dots-per-unit ratio. Smaller cohorts therefore render genuinely fewer dots than larger cohorts; per-cohort dot counts are not normalized for visual comparability.

## Limitations

### Sources of uncertainty (overview)

The dot placement on the map carries uncertainty from three stacked decisions, in roughly decreasing order of magnitude:

1. **The trait vector that defines each cohort.** This is the largest source of uncertainty and is irreducibly subjective. No statistical machinery can determine "what counts as a queer leftist" from data alone; the trait vector is an editorial operationalization of a cultural archetype. The per-cohort proxy-gap notes in `subcultures.yaml` document what the trait vector cannot capture.

2. **The choice of tract-level marginal variables.** Marginals are selected manually based on judgment about correlation with the cohort's expected geography, then constrained by what the Census Bureau publishes at tract level. Some natural choices (Table B16001 detailed-language, Table B11009 same-sex partner) are suppressed at the tract level and we substitute alternatives. Sensitivity to this selection is not formally characterized.

3. **The statistical estimation method (Fay-Herriot + ridge + NNLS + bootstrap + Conley).** This is the most heavily documented component below, but contributes the least uncertainty to actual dot placement. It primarily affects inferential statements about regression coefficients (whether they are well-identified), not where the dots appear on the map. Where a cohort lives is determined by the trait vector and chosen marginals; the statistical method only refines how dots scatter within each PUMA.

A reviewer's leverage on improving the map's accuracy is therefore highest at (1), moderate at (2), and lowest at (3). The remainder of this section addresses each of these and other limitations in detail.

**Trait vectors are correlate-based, not direct measurements.** Cultural attributes are not directly observable in census data; the vectors describe demographic, occupational, and behavioral correlates. Two cohorts with overlapping correlate profiles will produce similar geographic distributions even if the underlying cultural attributes differ.

**Several attributes are absent from census data.** Gender identity, sexual orientation beyond same-sex household composition, religion, political affiliation, and consumption preferences are not collected by the ACS. Cohorts whose defining attributes fall into these categories rely on correlated proxies; the proxy-gap notes record this per cohort.

**The same-sex household indicator covers only a portion of LGBTQ Californians.** Roughly 20% of LGBTQ adults are in same-sex partnerships at any given time, so cohort definitions that depend on this indicator systematically under-represent single LGBTQ residents.

**Cohort membership is sensitive to the threshold τ.** Membership is binary at the per-record level (a record is in or out of each cohort), but the rule that determines membership has one tunable parameter per cohort. Adjusting τ moves the cohort's membership boundary along the soft-fit gradient: a lower τ admits marginal qualifiers, a higher τ admits only textbook examples. Per-cohort sensitivity to τ has not been formally characterized in this implementation; a threshold sweep across `{0.3, 0.4, 0.5, 0.6, 0.7}` per cohort, reporting how member counts and tract-level geographies move, would be a natural extension. For cohorts where external benchmarks exist (Williams Institute LGBTQ population estimates, Pew language statistics, county-level voter-registration totals), τ can be calibrated against them.

**Cohorts can overlap.** Because cohorts are not mutually exclusive (a single individual may be a queer leftist *and* a bilingual baddie), sums of member counts across cohorts can exceed the state population. Within a single cohort, the count is a well-defined population total; across cohorts, the sum is interpretable only as the total of overlapping cohort participations, not as a partition of the state.

**Tract-level marginals are selected by judgment, not by automated procedure.** Each cohort's marginals are picked by the configurer based on intuition about correlation with the cohort's geography. We do not run lasso, forward/backward stepwise selection, or model-comparison metrics (AIC, BIC, AICc) to choose variables; those tools would only refine which already-chosen variables stay in the model. The decision of which variables to consider in the first place is editorial. This carries several specific risks:

- *Confirmation bias.* If a marginal is selected because the configurer expects it to predict the cohort's geography, the resulting dot placement will reflect that prior. The R² and LOOCV R² metrics measure how well the chosen marginals jointly predict each PUMA's direct estimate; neither validates that the chosen marginals are externally correct.

- *Census availability constraint.* Marginals are bounded by what the Census publishes at tract level. Conceptually cleaner variables (Table B16001 detailed-language, Table B11009 same-sex partner) are tract-suppressed; we substitute broader categories (Table C16001 collapsed-language, Table B11001 nonfamily households), which lose specificity. Substitutions are documented per cohort.

- *Multicollinearity-driven dropout.* Tract-level count predictors at PUMA scale typically correlate strongly with PUMA population. NNLS+Ridge will zero a predictor when its variation is largely explained by population. A coefficient of zero should be read as "this predictor adds no information beyond what others already capture," not "this predictor is irrelevant to the cohort." VIF values are reported per coefficient so this can be interpreted directly.

- *Sensitivity not formally characterized.* Adding or removing a single marginal can change LOOCV R² substantially. For example, swapping the tract-suppressed Table B16001 (which returned all zeros at tract level) for the published Table C16001 was the move that gave the bilingual_baddie cohort a working tract-level marginal — its LOOCV R² is now ≈ 0.82. We have not quantified per-cohort sensitivity to marginal-set perturbation; a leave-one-marginal-out R² delta would be a natural extension.

- *No external validation.* The pipeline produces estimates without comparison to independent ground truth (Williams Institute LGBTQ population estimates, Pew language statistics, county-level voter registration totals). Each cohort's tract-level distribution is therefore as accurate as the correlation between the chosen marginals and the unobserved true cohort geography; we have no external check on that correlation. External validation is the single highest-leverage methodological improvement available beyond the current state.

**PUMS is a sample, not a complete enumeration.** The 5-year file pools roughly 5% of California's population across the 2019–2023 surveys. Sampling weights are used throughout. Per-PUMA sampling variances of the cohort estimates are computed from the 80 successive-difference replicate weights and propagated into the small-area estimation step via the Fay-Herriot EBLUP. PUMAs with very few matching cohort records have large σ²_e_p and shrink toward the regression line; PUMAs with many records preserve their direct estimate. The shrinkage factors γ_p are reported per cohort.

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

**Computational reproducibility under parallel execution.** The pipeline parallelises cohort processing and bootstrap resampling via `joblib`. Bootstrap resamples are seeded from a master RNG with deterministic per-resample sub-seeds (the standard parallel-RNG pattern in L'Ecuyer 2002, *Operations Research* 50(6), 1073–1075), so coefficient samples are bit-identical whether the pipeline runs serially or in parallel. The cohort-level parallelism uses process-based workers (`joblib`'s loky backend) so each cohort has isolated BLAS state and per-cohort outputs are deterministic. Two runs of the pipeline at the same configuration and the same input data produce identical `model_summaries.json`, `tract_scores.json`, and `summary.json` regardless of `n_jobs` settings.

## References

- Anselin, L. (1988). *Spatial Econometrics: Methods and Models*. Kluwer Academic Publishers.
- Battese, G. E., Harter, R. M., & Fuller, W. A. (1988). An error-components model for prediction of county crop areas using survey and satellite data. *Journal of the American Statistical Association*, 83(401), 28–36.
- Beckman, R. J., Baggerly, K. A., & McKay, M. D. (1996). Creating synthetic baseline populations. *Transportation Research Part A*, 30(6), 415–429.
- Belsley, D. A., Kuh, E., & Welsch, R. E. (1980). *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*. Wiley.
- Bester, C. A., Conley, T. G., & Hansen, C. B. (2011). Inference with dependent data using cluster covariance estimators. *Journal of Econometrics*, 165(2), 137–151.
- Cliff, A. D., & Ord, J. K. (1981). *Spatial Processes: Models and Applications*. Pion.
- Conley, T. G. (1999). GMM estimation with cross sectional dependence. *Journal of Econometrics*, 92(1), 1–45.
- Deming, W. E., & Stephan, F. F. (1940). On a least squares adjustment of a sampled frequency table when the expected marginal totals are known. *Annals of Mathematical Statistics*, 11(4), 427–444.
- Efron, B., & Tibshirani, R. (1993). *An Introduction to the Bootstrap*. Chapman & Hall.
- Fay, R. E., & Herriot, R. A. (1979). Estimates of income for small places: An application of James-Stein procedures to census data. *Journal of the American Statistical Association*, 74(366), 269–277.
- Gonzalez, M. E. (1973). Use and evaluation of synthetic estimators. *Proceedings of the Social Statistics Section, American Statistical Association*, 33–36.
- Hanley, J. A., & McNeil, B. J. (1982). The meaning and use of the area under a receiver operating characteristic (ROC) curve. *Radiology*, 143(1), 29–36.
- Hastie, T., Tibshirani, R., & Friedman, J. (2009). *The Elements of Statistical Learning* (2nd ed.). Springer.
- Hoerl, A. E., & Kennard, R. W. (1970). Ridge regression: Biased estimation for nonorthogonal problems. *Technometrics*, 12(1), 55–67.
- Lawson, C. L., & Hanson, R. J. (1974). *Solving Least Squares Problems*. Prentice-Hall.
- L'Ecuyer, P. (2002). An object-oriented random-number package with many long streams and substreams. *Operations Research*, 50(6), 1073–1075.
- LeSage, J. P., & Pace, R. K. (2009). *Introduction to Spatial Econometrics*. CRC Press.
- Moran, P. A. P. (1950). Notes on continuous stochastic phenomena. *Biometrika*, 37(1/2), 17–23.
- Müller, U. K., & Watson, M. W. (2017). Low-frequency econometrics. *Econometrica*, 85(4), 1057–1099.
- Pepe, M. S. (2003). *The Statistical Evaluation of Medical Tests for Classification and Prediction*. Oxford University Press.
- Prasad, N. G. N., & Rao, J. N. K. (1990). The estimation of the mean squared error of small-area estimators. *Journal of the American Statistical Association*, 85(409), 163–171.
- Rao, J. N. K., & Molina, I. (2015). *Small Area Estimation* (2nd ed.). Wiley.
- Solnit, R. (2010). *Infinite City: A San Francisco Atlas*. University of California Press.
- Tanton, R., & Edwards, K. L. (Eds.). (2013). *Spatial Microsimulation: A Reference Guide for Users*. Springer.
- U.S. Census Bureau. (2023). *PUMS Accuracy of the Data*. American Community Survey documentation.
- Williamson, P., Birkin, M., & Rees, P. H. (1998). The estimation of population microdata by using data from small area statistics and samples of anonymised records. *Environment and Planning A*, 30(5), 785–816.
- Wolter, K. M. (2007). *Introduction to Variance Estimation* (2nd ed.). Springer.
- Zadeh, L. A. (1983). A computational approach to fuzzy quantifiers in natural languages. *Computers & Mathematics with Applications*, 9(1), 149–184.
