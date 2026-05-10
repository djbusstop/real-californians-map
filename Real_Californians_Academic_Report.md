# Where Real Californians Live: Imagined Geographies, Census Proxies, and the Cartography of Cultural Archetypes

**Project:** *Where Real Californians Live* (working title: California Culture Map)
**Date:** May 2026

---

## Abstract

This report describes the framing, methodology, results, and limitations of *Where Real Californians Live*, an interactive cartographic project that operationalizes named cultural archetypes (the "queer leftist," the "bilingual baddie," the "Crumbl cookie couple," the "toothless hill people," among others) as weighted vectors of variables drawn from the U.S. Census Bureau's American Community Survey Public Use Microdata Sample. The project sits in the lineage of speculative and critical cartography, treating the map less as an instrument for measuring cultural geography than as a medium for testing whether intuitive cultural categories carry any demographic anchoring at all. Methodologically it combines a soft-scoring archetype model at the person-record level with a Fay–Herriot small-area estimation procedure that distributes Public Use Microdata Area (PUMA) cohort estimates across census tracts. Results sort cohorts into three distinct patterns, each of which is informative about the archetype rather than only about the model. The project documents the irreducibly editorial component of its work alongside the rigorously statistical one.

**Keywords:** imagined geographies, critical cartography, ACS PUMS, small-area estimation, Fay–Herriot model, cultural geography, California.

---

## 1. Introduction: Mapping as Performance

*Where Real Californians Live* asks an unusual question. When a cultural archetype (a "queer leftist," a "Crumbl cookie couple," a "toothless hill person") is operationalized as a vector of demographic, occupational, and household variables drawn from the American Community Survey, does the resulting geography match the one that motivated the archetype in the first place? The answer differs by archetype, and the difference is the substantive contribution.

The project sits between two more familiar postures. It does not assume cultural stereotypes are objectively true and that a sufficiently good dataset will reveal their geography. Nor does it assume stereotypes are mere fabrications with no demographic correlate. It treats each archetype's trait vector as a *hypothesis* about the world rather than a *measurement* of it.

This posture is best articulated by the distinction Gilles Deleuze and Félix Guattari (1987, 12) drew between **mapping** and **tracing**. A tracing reproduces an unconscious closed in upon itself, an "alleged competence" that already knows what it depicts. A map, by contrast, "is entirely oriented toward an experimentation in contact with the real" and "has to do with *performance*" rather than competence. James Corner (1999), drawing the distinction explicitly into cartographic theory, argues that maps are agents that *produce* rather than represent the territories they describe, capable of uncovering realities previously unseen or unimagined even across seemingly exhausted grounds. *Where Real Californians Live* is on the map side of that line. The trait vectors are not tracings of a pre-existing demographic California; they are performances that bring particular cohort geographies into legibility and then ask whether the data ratifies what the performance imagined.

This places the project alongside Rebecca Solnit's *Infinite City: A San Francisco Atlas* (2010) and the broader tradition of critical and speculative cartography (Harley 1989; Wood 1992; Cosgrove 1985), which treats geographic data as a substrate for rendering social imaginaries rather than for measuring objective truths. Edward Said's (1978) earlier formulation of "imagined geographies" supplies the underlying premise that representation partly constitutes the geographies people experience as real, but the present work prefers Corner's performative frame to Said's representational one.

The verification criterion follows directly from this performative commitment. A cohort's trait vector is judged not against an external ground truth, which does not exist for cultural archetypes, but against the **imagined geography** held by the cohort definer at the time of specification. The test is whether the rendered map matches what the author had in mind when naming the cohort. The criterion is self-referential rather than externally referential, and it is verifiable in the sense that the imagined geography can be documented per cohort in advance, with concordance against the rendered output assessed afterward. Discordance is then a finding about the author's imagination meeting the data, not a model failure. Each cohort in the published library is paired with a brief pre-registered description of the imagined geography that motivated its trait vector, and the diagnostic taxonomy in Section 8 functions as a vocabulary for describing concordance with that imagination rather than as a falsification test against external reality.

The trait vector for each cohort is therefore the hypothesis. Some categories validate cleanly. The bilingual baddie (young, female, non-English at home, service or healthcare-support work, lower-middle income, lives with family or roommates) maps closely onto Spanish-language and Hispanic-population geography in California, which is what the author imagined. Other categories anchor poorly. The married-gays cohort exists at scale only in a handful of historical enclaves (the Castro, West Hollywood, Palm Springs) rather than as a smooth demographic gradient, and its model fits accordingly. Both outcomes are findings about the relationship between the author's imagination and the demographic record: a cohort that maps tightly demonstrates demographic anchoring of the imagined archetype; a cohort that maps loosely demonstrates that the archetype, as imagined, lives in cultural-historical specificity beyond what census variables can reach.

The project has two primary deliverables, each of which is a substantive contribution in its own right. The first is a **subculture library**, a curated set of named archetypes paired with explicit trait vectors and "proxy-gap notes" documenting what each vector cannot capture. The library is the project's thesis about California's subcultural geography. The second is the **interactive map** itself, which renders the cohorts over California's 281 PUMAs and approximately 9,000 census tracts using contemporary best-practice methods for small-area cohort allocation: a Fay–Herriot area-level model with non-negative ridge regression, EBLUP shrinkage informed by replicate-weight sampling variances, and tract-level raking to the EBLUP totals. The map is therefore both a presentation surface for the library and, in its own right, a worked contribution to the cartography of survey-derived cultural cohorts.

## 2. Theoretical and Methodological Precedents

Four strands inform the work.

The first is the **critical-cartographic** insistence that no map is neutral (Harley 1989; Wood 1992; Cosgrove 1985). The choice of which variables to include, which categories to gate on, and which marginals to spatialize are editorial acts. The methodology surfaces those acts rather than burying them in defaults; the proxy-gap notes are part of the published configuration.

The second is the **speculative-atlas** tradition exemplified by Solnit's *Infinite City* (2010) and predecessors such as Joel Garreau's *Nine Nations of North America* (1981) and the *Los Angeles Times* "Mapping L.A." project (2009). These works treat a curated library of named places or regions as the primary deliverable, with any single map serving the larger argument. *Where Real Californians Live* follows that convention: working backward from named archetypes is editorial, ships faster than a user-trait input system, and produces an artifact that can be discussed independently of the rendering.

Two recent atlas projects warrant explicit comparison. Dante Chinni and James Gimpel's *Our Patchwork Nation* (2010) defines twelve American community types from county-level demographic and economic variables and uses the typology to explain political and cultural geography. The methodological move (define cohorts as multidimensional types, then map them onto geography) is structurally similar to this project, with two differences: their unit is the county and their typology was derived bottom-up by clustering, whereas this project's unit is the PUMA-and-tract pair and the typology is editorially specified. Colin Woodard's *American Nations* (2011) provides a useful **inverse** framing. Woodard draws borders around eleven culturally homogeneous regions and argues those regions explain American political and cultural divisions. *Where Real Californians Live* runs the opposite procedure. It does not draw cultural borders; it locates individuals who fit a trait vector, allowing the resulting concentrations to emerge wherever the demographic signal lands rather than imposing a regional partition. Woodard asks where the borders of cultural regions lie. This project asks how individuals matching a cultural type are dispersed across an existing geography.

The third strand, less commonly invoked in cartographic projects but conceptually closer than the rest, is **Pierre Bourdieu's social topology** (1984). Bourdieu mapped class fractions in a multidimensional space of economic and cultural capital using survey data, treating each social position as a vector of dispositions and resources. The parallel with this project is at the level of *concept* rather than method: each subculture is a position in a high-dimensional space of demographic, occupational, and household attributes, located by its trait vector and assessed against PUMS data.

The methodological parallel does not hold, and the inversion deserves explicit naming. Bourdieu derived social positions *bottom up* from observed practices via multiple correspondence analysis, an inductive procedure. This project specifies positions *top down* from editorial judgment and asks the data to ratify them, a deductive procedure. These are reverse epistemic operations. *Habitus* in Bourdieu's sense is embodied, acquired through socialization, and held to *generate* practice; a trait vector is operational rather than generative, classifying individuals from the outside without claiming they have internalized the schema. Bourdieu's topology was a *finding*. This project's topology is a *prior*. The inheritance is therefore conceptual, not methodological: the project sits closer to a deductive application of habitus-style thinking than to the inductive reconstruction habitus theory itself requires.

The fourth strand is **small-area estimation** in survey statistics (Fay and Herriot 1979; Rao and Molina 2015), the technical machinery that allows PUMA-resolution PUMS estimates to be redistributed at tract resolution under principled variance accounting. This component lends quantitative discipline to a project whose framing is otherwise humanities-leaning.

## 3. Data Sources

All data are public and free, sourced from the U.S. Census Bureau.

The primary input is the **2023 5-Year American Community Survey Public Use Microdata Sample (PUMS)**, covering the survey years 2019 through 2023. The PUMS is an anonymized individual-record extract of approximately five percent of the California population: roughly 2,000,000 person records and 830,000 housing-unit records. It carries detailed person-level attributes (age, sex, race, education, occupation, industry, income subtypes, commute mode, language at home, disability, marital status, military service, school enrollment) and household-level attributes (tenure, household type, units in structure, year built, lot size, heating fuel, agricultural sales, broadband subscription, vehicles available). The lowest geographic identifier exposed by PUMS is the PUMA, of which California has 281 in the 2020 vintage, each containing approximately 100,000 residents.

The 5-Year file is preferred over the 1-Year file at this scale because narrow trait vectors (for instance, those gated on `SAME_SEX = 1` or `INDP = 11`, agriculture) produce small per-PUMA cohorts whose sampling variance under a single-year sample is high enough to dominate downstream estimation.

Tract-level **ACS 5-Year Detailed Tables** provide pre-tabulated cross-tabs across approximately 9,000 California tracts for the marginals used in the small-area allocation step. **TIGER/Line shapefiles** supply tract and state boundary geometry, and a **Census Bureau crosswalk** maps 2020 census tracts to 2020 PUMAs.

## 4. The Subculture Model

Each subculture is defined as a configuration record with three components.

First, a **trait vector** of weighted conditions over PUMS variables. Each condition takes one of several operator forms: equals, in-set, in-range, gte, lte, percentile-gte, NAICS-mapped industry, or SOC-mapped occupation. Each condition carries a non-negative weight, and any condition can be marked as `required` to function as a hard gate.

Second, a **set of tract-level marginals**, ACS aggregated-table variables used to distribute each PUMA-level cohort estimate across the tracts within that PUMA. The marginal is selected to correlate with the cohort's expected geography. For example, the toothless-hill-people cohort uses mobile-home unit counts (Table B25024_010E) and SNAP recipient households (Table B22002_002E) as rural marginal-housing proxies.

Third, a **proxy-gap note** documenting categorical attributes the trait vector cannot capture: gender identity, sexual orientation beyond same-sex household composition, religion, political affiliation, and consumption preferences. These notes are part of the published configuration as a methodological commitment to transparency.

The configuration follows one explicit modeling constraint: no geographic gating is applied. Cohorts are not restricted to specific PUMAs, counties, or regions, so any spatial concentration emerges from the demographic and behavioral signals rather than from a pre-imposed geography. Hard gates within the trait vector are reserved for traits that structurally define category membership rather than that score it.

## 5. Scoring and Membership

The membership rule is two-stage. First a continuous fit score is computed per record. Then a per-cohort threshold is applied to derive a binary cohort membership indicator. The PUMA-level estimand is the weighted count of cohort members, a well-defined population total in the standard small-area-estimation sense.

This formulation is a deliberate departure from a fuzzy-set scoring approach in which the PUMA-level estimand was the PWGTP-weighted sum of soft similarity scores. The fuzzy-set quantity is well defined as a σ-count (Zadeh 1983) but it is not a population total, and applying Fay-Herriot machinery to it conflates a fuzzy cardinality with a count. Threshold-based membership produces a quantity the downstream machinery is designed for and connects directly to standard practice in synthetic-population microsimulation (Beckman, Baggerly, and McKay 1996; Williamson, Birkin, and Rees 1998; Tanton and Edwards 2013).

**Stage 1: Fit score.** For each PUMS person record and each subculture, a continuous fit score in `[0, 1]` is computed. Each condition in the trait vector returns 1 if satisfied and 0 otherwise. If any condition marked `required` returns 0, the gate fails closed and the fit score is 0. Otherwise:

```
fit(record, s) = Σ_i w_i · 1{condition_i satisfied} / Σ_i w_i
```

where `w_i` are the condition weights. Records that exactly satisfy the full vector score 1; records that pass all gates but match no soft conditions score the gate-only baseline (the share of total weight contributed by required conditions).

**Stage 2: Membership indicator.** Each cohort declares a threshold `τ ∈ (0, 1]` (default 0.5, settable in the YAML `settings` block, overridable per cohort). A record counts as a cohort member iff its gate evaluates True AND its fit score is at or above τ:

```
member(record, s) = 1   if   gate(record, s)   AND   fit(record, s) ≥ τ_s
                  = 0   otherwise
```

The threshold operationalizes "how exclusive is this cohort" and is the place where editorial intent about cohort exclusiveness is concentrated. Where external benchmarks exist (Williams Institute LGBTQ population estimates, Pew language statistics, county voter-registration totals), τ can be calibrated against them. Where they do not, τ is chosen editorially with stated rationale. The structural analogue is operating-point selection on a continuous decision function in classifier evaluation (Hanley and McNeil 1982; Pepe 2003).

**Stage 3: PUMA aggregation.** Each member indicator is weighted by the record's sampling weight `PWGTP` (the integer count of real Californians the record represents) and summed by PUMA:

```
y_p(s) = Σ_{r ∈ p} member(r, s) · PWGTP_r
```

`y_p(s)` is the weighted count of cohort members in PUMA p: a well-defined population total that the downstream Fay-Herriot, SDR, and raking machinery operates on in the standard sense. Sums across cohorts can still exceed the state population because cohorts are not mutually exclusive, but within a single cohort `y_p(s)` is a count, not a fuzzy quantity.

**Secondary diagnostics.** The soft fit score is retained per cohort as a within-cohort secondary diagnostic. Three quantities are reported per cohort in `summary.json` and `model_summaries.json`: the **weighted gate-pass count** (records that pass the cohort's required conditions before the threshold filter), the **weighted soft total** (Σ fit_score × PWGTP, the previous primary estimand under fuzzy-set scoring), and the **mean fit per member** (the average fit score among members). The mean fit per member is the most useful diagnostic for threshold tuning: values close to 1 indicate the cohort is dominated by textbook examples, values close to τ indicate marginal qualifiers and suggest τ may be too low for the cohort's editorial intent.

## 6. Geographic Distribution: Fay–Herriot Small-Area Estimation

Tract-level resolution is achieved through a four-step area-level small-area-estimation procedure operating on the per-PUMA member count `y_p(s)` produced by the scoring stage. Operating at the area level (rather than fitting a unit-level model) reflects the fact that PUMS records carry no tract identifier under Census Bureau disclosure rules, so direct tract-level estimation from microdata is not feasible.

**Step 1: Non-negative ridge regression.** For each cohort, a design matrix is built with PUMA population and the cohort's declared marginals (aggregated from tract to PUMA). Predictors are z-score standardized so the L2 ridge penalty applies uniformly across columns of different scales (Hastie, Tibshirani, and Friedman 2009). Ridge regularization (Hoerl and Kennard 1970) is used to address the strong multicollinearity between count predictors and PUMA population. Non-negativity is enforced via Lawson and Hanson (1974) NNLS because both predictors and response are non-negative counts; a negative coefficient would imply a count predictor *suppresses* cohort membership, which is conceptually awkward without structural justification. The penalty parameter λ is selected per cohort by leave-one-PUMA-out cross-validation across the grid `{0, 0.1, 1, 10, 100, 1000, 10000}`.

**Step 2: Successive-difference replication for sampling variance.** PUMS ships with 80 successive-difference replicate weights. For each cohort and each PUMA the member count is computed 81 times (once with the main weight, once each with the 80 replicate weights), and the per-PUMA sampling variance of the count follows the Census-published formula (Wolter 2007):

```
Var(y_p) = (4 / 80) · Σ_r (y_{p,r} − y_p)²
```

With binary membership as input, this is the SDR variance of a population total, the canonical use case.

**Step 3: Fay–Herriot EBLUP shrinkage.** The Fay–Herriot (1979) area-level model is:

```
y_p = X_p β + u_p + e_p,    e_p ~ N(0, σ²_e_p),    u_p ~ N(0, σ²_u)
```

with σ²_u estimated by the Prasad and Rao (1990) method-of-moments estimator. The Empirical Best Linear Unbiased Predictor for each PUMA is:

```
ŷ_FH_p = X_p β̂ + γ_p · (y_p − X_p β̂),    γ_p = σ̂²_u / (σ̂²_u + σ²_e_p)
```

When per-PUMA sampling variance is large (small cohort, high noise), γ_p is small and the EBLUP shrinks toward the regression line. When the variance is small, the direct estimate is preserved. This is the canonical small-area-estimation tradeoff between synthetic bias and direct-estimate variance.

**Step 4: Tract-level allocation by raking.** For each tract within a PUMA, the regression predicts a raw count, negative predictions are clipped to zero, and within-PUMA tract counts are proportionally rescaled (raked, in the sense of Deming and Stephan 1940; Rao and Molina 2015) so they sum to the EBLUP rather than the noisy direct estimate. Using the EBLUP as the raking target is what propagates the sampling-variance correction down to the tract level.

**Inference.** Two complementary inference statements are reported per coefficient: spatially-aware Conley (1999) standard errors with a Bartlett kernel and 75 km bandwidth (following Bester, Conley, and Hansen 2011), and non-parametric bootstrap percentile confidence intervals (Efron and Tibshirani 1993) over 1,000 PUMA resamples. Bootstrap resamples are seeded from a master RNG with deterministic per-resample sub-seeds following L'Ecuyer's (2002) parallel-RNG pattern, so coefficient samples are bit-identical whether the pipeline runs serially or in parallel. Diagnostic outputs further include in-sample and LOOCV R², residual standard deviation, Variance Inflation Factors (Belsley, Kuh, and Welsch 1980), the design-matrix condition number, and Moran's *I* (Moran 1950; Cliff and Ord 1981) on PUMA residuals under queen contiguity.

A fallback path applies when fewer than eight PUMAs carry valid data, the design matrix is singular, or LOOCV R² falls below 0.05: the cohort defaults to an equal-weight convex combination of normalized tract-marginal shares within each PUMA, a closed-form Iterative Proportional Fitting reduction.

## 7. Visualization

Tract-level estimates are rendered as randomly placed dots within tract polygons. The number of dots is `floor(tract_count / DOTS_PER_UNIT)`, with `DOTS_PER_UNIT` set to 20, so each visual dot corresponds to approximately 20 cohort members in that tract. Under the threshold-based membership rule the tract-level estimate is a weighted population count (the share of the PUMA member count allocated to the tract via raking), so the dot legend maps to a meaningful population quantity rather than a fuzzy-set cardinality. Random points are accepted by ray-casting point-in-polygon test against tract geometry pre-clipped to the California land cartographic boundary, so no dots fall on water. Multiple cohorts may be rendered simultaneously, with each cohort assigned a distinct color and the combined dot feature collection randomly shuffled (Fisher–Yates) to prevent systematic paint-order bias when several cohorts overlap.

## 8. Findings

The project's epistemic posture is unusual for a quantitative geographic study, and the diagnostics described above serve a dual role. They are checks on the regression's statistical properties, but they are also evidence about whether each cohort's trait vector has rendered the geography its author imagined when specifying it (per the verification criterion articulated in Section 1). Three patterns of concordance between imagined and rendered geography coexist in the results, and each carries a different meaning.

**Broadly distributed archetypes.** Some cultural categories describe a substantial fraction of the population whose geography maps roughly to total population. The "Crumbl cookie couple" cohort, defined by young married homeowners with mortgages, two cars, and middle-class incomes, is found across most suburban California rather than concentrated in any specific neighborhood type. The model captures this correctly with high R² and small residual Moran's *I*. The finding is that this archetype is genuinely diffuse, a feature of mainstream consumer culture rather than a localized subculture, and a "broadly distributed" outcome here is the right answer.

**Demographically anchored archetypes.** Some archetypes track specific census variables sharply and reveal sharp geography. The "bilingual baddie" cohort maps closely onto Spanish-language and Hispanic-population geography. Iterative refinement of marginal selection visibly improved the operationalization: LOOCV R² rose from approximately 0.64 to 0.74 simply by swapping the tract-suppressed Table B16001 (detailed language) for the published Table C16001 (collapsed language). The "toothless hill people" cohort (rural, low-income, on Social Security and SNAP, in older mobile homes with propane or wood heat) likewise resolves cleanly to the rural northern-mountain and Sierra-foothill geography that motivated the archetype. In both cases R² and LOOCV R² rose together while residual Moran's *I* fell, the pattern of three diagnostics moving in concert that signals genuine progress in marginal selection rather than overfitting.

**Historically clustered archetypes.** Some archetypes live in cultural-historical patterns that demographic predictors cannot reach. The "married gays" cohort (same-sex married couples of any age) exists at scale only in a handful of historical enclaves shaped by decades of migration. Its regression R² is moderate even with carefully chosen marginals, and residual Moran's *I* stays significantly positive. This is not a model failure; it is a finding that the cohort lives in cultural-historical specificity, the residue of established enclaves persisting through cultural memory rather than current demographic mix.

These three patterns are the project's substantive contribution. They show that "stereotype" is not a single epistemic category but several. Some archetypes track real, broad demographic structures. Others track real, sharp demographic structures. Still others track historical and cultural memory whose footprint demographic data records only obliquely. A high residual Moran's *I* is a problem when the archetype is supposed to be broadly distributed but a finding when the archetype is supposed to be culturally clustered. The diagnostics must be read in conversation with the archetype's editorial intent rather than as standalone pass-fail tests.

A subsidiary finding concerns the precision-detection relationship. The same diagnostic value carries different evidential weight at different signal-to-noise ratios because residuals are a sum of measurement noise and unexplained structure. When σ²_e is large, residuals are dominated by noise and any underlying spatial pattern is masked. As σ²_e drops (for instance, by moving from 1-Year to 5-Year ACS PUMS), previously-masked spatial structure becomes measurable, and a Moran's *I* residual that was statistically non-significant under high-variance estimation can become significant under lower-variance estimation without any change to model specification. A jump in residual Moran's *I* after improving estimation precision is therefore a sign the diagnostic is now seeing real spatial structure rather than its noise-blurred image.

## 9. Limitations

Uncertainty in the project's outputs stacks across three decisions, listed in roughly decreasing order of contribution to final dot placement.

**Trait vector and threshold specification (largest, irreducibly editorial).** No statistical procedure can determine "what counts as a queer leftist" from data alone; the trait vector and the membership threshold τ together are an editorial operationalization of a cultural archetype. The proxy-gap notes in `subcultures.yaml` document what each vector cannot capture. Several attributes are simply absent from ACS data: gender identity, sexual orientation beyond same-sex household composition, religion, political affiliation, and consumption preferences. A reviewer's leverage on improving the map is highest at this layer.

**Marginal selection (moderate).** Tract-level marginals are picked by judgment about correlation with the cohort's expected geography, then constrained by what the Census publishes at tract level. Several natural choices, including Table B16001 (detailed language) and Table B11009 (same-sex partner households), are tract-suppressed for disclosure reasons; the substitutes (Tables C16001 and B11001 respectively) lose specificity. Per-cohort sensitivity to marginal selection is not formally characterized; a leave-one-marginal-out R² delta would be a natural extension. There is also no external validation against independent ground truth (Williams Institute LGBTQ population estimates, Pew language statistics, county-level voter-registration totals), and external validation is the single highest-leverage methodological improvement available beyond the current state.

**Statistical estimation method (smallest).** Despite being the most heavily documented component, the Fay–Herriot, ridge, NNLS, bootstrap, and Conley pipeline contributes the least to dot placement. It primarily affects inferential statements about regression coefficients rather than where dots fall on the map.

Several other limitations bear naming.

The **same-sex household indicator** captures only the partnered fraction of LGBTQ adults, roughly twenty percent. Single LGBTQ residents are invisible in any cohort that gates on `SAME_SEX = 1`.

**Cohort membership is sensitive to the threshold τ.** Membership is binary at the per-record level under the threshold-based rule, but the rule has one tunable parameter per cohort. Lowering τ admits marginal qualifiers; raising τ admits only textbook examples. Per-cohort sensitivity to τ has not been formally characterized; a threshold sweep across a small grid (e.g., {0.3, 0.4, 0.5, 0.6, 0.7}) per cohort, reporting how member counts and tract-level geographies move, would be a natural extension. Where external benchmarks are available, τ can be calibrated against them; otherwise τ is editorial.

**Cohorts can overlap.** Cohorts are not mutually exclusive: a single individual may be a queer leftist *and* a bilingual baddie. Sums of member counts across cohorts can therefore exceed the state population. Within any single cohort, the count is a well-defined population total; across cohorts, the sum is the total of overlapping cohort participations, not a partition of the state.

**Residuals exhibit significant positive spatial autocorrelation** across nearly every cohort (Moran's *I* typically 0.27 to 0.42, *z* > 7, *p* < 10⁻¹⁵ under the normality assumption). A non-spatial specification was retained deliberately because the unit of inference is the PUMA and the project is descriptive cartography rather than spatial econometrics. Future work could fit a spatial-lag model `y = ρWy + Xβ + ε` in the sense of Anselin (1988) or LeSage and Pace (2009) to absorb this residual structure.

**Influential-observation diagnostics** (hat-matrix leverage, Cook's distance) are not currently reported per cohort. Standard remedies (Belsley, Kuh, and Welsch 1980) would be a natural extension.

**Cartographic clipping is at 1:500,000 scale**, so coastlines and tract boundaries near water are simplified.

### Ethical and reflexive positioning

The project does not claim a view from nowhere. Its trait vectors and cohort names encode the perspective of an editorially situated author who is making cultural categories visible at neighborhood resolution using public-domain demographic data. Because making the imagined visible at scale is itself a cartographic act with consequences, the project's standpoint deserves explicit treatment alongside its statistical limitations.

Three strands of literature bear directly on this position. Donna Haraway's "Situated Knowledges" (1988) is the foundational reference for the position the project has implicitly taken: knowledge is partial, perspectival, and accountable to the standpoint from which it is produced. The project's per-cohort proxy-gap notes are a Haraway-style commitment to documenting the partiality of the view, whether named as such or not. Catherine D'Ignazio and Lauren Klein's *Data Feminism* (2020) extends the situated-knowledge commitment specifically to data work, asking whose interests data work serves and what counts as situated knowledge in data science. Wendy Hui Kyong Chun's *Discriminating Data: Correlation, Neighborhoods, and the New Politics of Recognition* (2021) is the sharpest contemporary intervention on the cartographic problem this project enacts. Chun's argument is that neighborhood-scale demographic data participates in producing the categories it claims to find, and that the politics of recognition this entails are not neutral.

Three positioning claims follow from these literatures and apply to this project specifically.

First, the cohort names are asymmetric in tone. Some are affectionate ("queer leftist," "bilingual baddie"). Others are derisive ("toothless hill people," "crazy person on the bus"). The asymmetry is not an accident of editorial labor; it is a deliberate aesthetic choice the author owns. The cohort names represent the stereotypes the author holds about the populations they describe, rendered legible enough that their demographic anchoring can be tested. The names do not claim that the populations are reducible to the names; they claim only that this is the register in which the author imagines them. The performative-mapping commitment articulated in Section 1 makes this distinction load-bearing. The project does not foreclose the possibility that a different author, working from a different position, would name the cohorts differently, and any such re-authoring would constitute a different project rather than a correction to this one.

Second, the project does not claim that the named categories exist independently of its naming them. It claims only that *the categories the author imagines* have the demographic anchoring the trait vectors operationalize, and that the rendered map is a faithful presentation of where individuals matching those vectors are likely to live. The map participates in producing the categories it names, and the author owns that production rather than disclaiming it.

Third, the audience of the project is implied rather than specified. The map is published on the public web in a form intelligible to a literate non-specialist reader; it does not require institutional credentials to interpret. This deliberately broad audience carries responsibility. The cartographic surfacing of severe disability ("crazy person on the bus") and rural poverty ("toothless hill people") at neighborhood resolution makes those populations visible to viewers who are unlikely to be members of those populations and who may exercise authority (policy, policing, real estate) over them. The project's editorial license to name does not extend to license over how the resulting maps are subsequently used, and the author cannot foreclose harmful downstream readings. Acknowledging this is part of the project's standpoint, not separate from it.

## 10. Discussion and Future Work

The project's hybrid posture, rigorously statistical at the level of any single estimate but unapologetically subjective at the level of cohort definition, is constitutive rather than incidental. The diagnostics test a hypothesis about how an archetype meets the data. The hypothesis can succeed or fail in different ways depending on the archetype's underlying geographic shape, and a failed test is itself a finding about the archetype, not only about the model. This is the third position the framing in Section 1 set out to occupy.

Three near-term extensions would meaningfully strengthen the project. First, **external validation** against published cohort estimates would convert each cohort from an internally-coherent estimate into one with an external benchmark. Second, **formal sensitivity analysis** (leave-one-marginal-out and leave-one-condition-out) would quantify the editorial fragility of each cohort's geography. Third, a **spatial-lag specification** would absorb the residual spatial autocorrelation that the present descriptive model leaves unexplained.

A longer-horizon question concerns generalization beyond California. The PUMA-level inference and tract-level allocation pipeline transfer to any U.S. state without modification. Trait vectors are state-specific in their cultural references but methodologically portable. A "Texas Culture Map" or "New York Culture Map" would offer a useful comparative test of which archetypes generalize and which are state-locked, and would let us ask which features of subcultural identity are robustly demographic and which are irreducibly local.

## 11. Conclusion

*Where Real Californians Live* operationalizes named cultural archetypes as census-data trait vectors and asks whether those vectors anchor to real geography. Its framing draws on Deleuze and Guattari's distinction between mapping and tracing as developed in Corner's cartographic theory, Bourdieu's social topology, and Solnit's speculative-atlas tradition, all underpinned by the critical-cartographic insistence that maps are arguments rather than measurements. Its methodology combines person-record similarity scoring with Fay–Herriot small-area estimation, ridge regularization with non-negativity constraints, and complementary Conley and bootstrap inference. Its findings sort archetypes into three patterns (broadly distributed, demographically anchored, historically clustered), each of which is informative about the archetype itself rather than only about the model. Its limitations, particularly the irreducible subjectivity of trait-vector specification and the absence of external validation, are documented rather than hidden. The project delivers two things at once: a curated subculture library that constitutes a thesis about California, and an interactive map that applies contemporary best-practice methods for small-area cohort allocation to render that thesis visible.

---

## References

Anselin, Luc. 1988. *Spatial Econometrics: Methods and Models*. Dordrecht: Kluwer Academic Publishers.

Beckman, Richard J., Keith A. Baggerly, and Michael D. McKay. 1996. "Creating Synthetic Baseline Populations." *Transportation Research Part A* 30 (6): 415–429.

Belsley, David A., Edwin Kuh, and Roy E. Welsch. 1980. *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*. New York: Wiley.

Bester, C. Alan, Timothy G. Conley, and Christian B. Hansen. 2011. "Inference with Dependent Data Using Cluster Covariance Estimators." *Journal of Econometrics* 165 (2): 137–151.

Bourdieu, Pierre. 1984. *Distinction: A Social Critique of the Judgement of Taste*. Translated by Richard Nice. Cambridge, MA: Harvard University Press.

Chinni, Dante, and James Gimpel. 2010. *Our Patchwork Nation: The Surprising Truth About the "Real" America*. New York: Gotham Books.

Chun, Wendy Hui Kyong. 2021. *Discriminating Data: Correlation, Neighborhoods, and the New Politics of Recognition*. Cambridge, MA: MIT Press.

Cliff, Andrew D., and J. Keith Ord. 1981. *Spatial Processes: Models and Applications*. London: Pion.

Conley, Timothy G. 1999. "GMM Estimation with Cross Sectional Dependence." *Journal of Econometrics* 92 (1): 1–45.

Corner, James. 1999. "The Agency of Mapping: Speculation, Critique and Invention." In *Mappings*, edited by Denis Cosgrove, 213–252. London: Reaktion Books.

Cosgrove, Denis. 1985. "Prospect, Perspective and the Evolution of the Landscape Idea." *Transactions of the Institute of British Geographers* 10 (1): 45–62.

Deleuze, Gilles, and Félix Guattari. 1987. *A Thousand Plateaus: Capitalism and Schizophrenia*. Translated by Brian Massumi. Minneapolis: University of Minnesota Press.

D'Ignazio, Catherine, and Lauren F. Klein. 2020. *Data Feminism*. Cambridge, MA: MIT Press.

Deming, W. Edwards, and Frederick F. Stephan. 1940. "On a Least Squares Adjustment of a Sampled Frequency Table When the Expected Marginal Totals Are Known." *Annals of Mathematical Statistics* 11 (4): 427–444.

Efron, Bradley, and Robert Tibshirani. 1993. *An Introduction to the Bootstrap*. New York: Chapman & Hall.

Fay, Robert E., and Roger A. Herriot. 1979. "Estimates of Income for Small Places: An Application of James-Stein Procedures to Census Data." *Journal of the American Statistical Association* 74 (366): 269–277.

Garreau, Joel. 1981. *The Nine Nations of North America*. Boston: Houghton Mifflin.

Hanley, James A., and Barbara J. McNeil. 1982. "The Meaning and Use of the Area under a Receiver Operating Characteristic (ROC) Curve." *Radiology* 143 (1): 29–36.

Haraway, Donna J. 1988. "Situated Knowledges: The Science Question in Feminism and the Privilege of Partial Perspective." *Feminist Studies* 14 (3): 575–599.

Harley, J. Brian. 1989. "Deconstructing the Map." *Cartographica* 26 (2): 1–20.

Hastie, Trevor, Robert Tibshirani, and Jerome Friedman. 2009. *The Elements of Statistical Learning*. 2nd ed. New York: Springer.

Hoerl, Arthur E., and Robert W. Kennard. 1970. "Ridge Regression: Biased Estimation for Nonorthogonal Problems." *Technometrics* 12 (1): 55–67.

Lawson, Charles L., and Richard J. Hanson. 1974. *Solving Least Squares Problems*. Englewood Cliffs, NJ: Prentice-Hall.

L'Ecuyer, Pierre. 2002. "An Object-Oriented Random-Number Package with Many Long Streams and Substreams." *Operations Research* 50 (6): 1073–1075.

LeSage, James P., and R. Kelley Pace. 2009. *Introduction to Spatial Econometrics*. Boca Raton: CRC Press.

*Los Angeles Times*. 2009. "Mapping L.A." *Los Angeles Times* online project.

Meyer, Ilan H. 2003. "Prejudice, Social Stress, and Mental Health in Lesbian, Gay, and Bisexual Populations: Conceptual Issues and Research Evidence." *Psychological Bulletin* 129 (5): 674–697.

Moran, Patrick A. P. 1950. "Notes on Continuous Stochastic Phenomena." *Biometrika* 37 (1/2): 17–23.

Pepe, Margaret S. 2003. *The Statistical Evaluation of Medical Tests for Classification and Prediction*. Oxford: Oxford University Press.

Prasad, Narasimha G. N., and J. N. K. Rao. 1990. "The Estimation of the Mean Squared Error of Small-Area Estimators." *Journal of the American Statistical Association* 85 (409): 163–171.

Rao, J. N. K., and Isabel Molina. 2015. *Small Area Estimation*. 2nd ed. Hoboken, NJ: Wiley.

Said, Edward W. 1978. *Orientalism*. New York: Pantheon Books.

Solnit, Rebecca. 2010. *Infinite City: A San Francisco Atlas*. Berkeley: University of California Press.

Tanton, Robert, and Kimberley L. Edwards, eds. 2013. *Spatial Microsimulation: A Reference Guide for Users*. Dordrecht: Springer.

U.S. Census Bureau. 2023. *PUMS Accuracy of the Data*. American Community Survey documentation.

Williamson, Paul, Mark Birkin, and Phil H. Rees. 1998. "The Estimation of Population Microdata by Using Data from Small Area Statistics and Samples of Anonymised Records." *Environment and Planning A* 30 (5): 785–816.

Wolter, Kirk M. 2007. *Introduction to Variance Estimation*. 2nd ed. New York: Springer.

Wood, Denis. 1992. *The Power of Maps*. New York: Guilford Press.

Woodard, Colin. 2011. *American Nations: A History of the Eleven Rival Regional Cultures of North America*. New York: Viking.

Zadeh, Lotfi A. 1983. "A Computational Approach to Fuzzy Quantifiers in Natural Languages." *Computers & Mathematics with Applications* 9 (1): 149–184.
