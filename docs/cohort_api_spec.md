# Cohort API Spec

Data contract between the frontend chatbot/map and the FastAPI backend that
scores user-defined cohorts against the existing Python pipeline.

This document is the working spec. It describes the request and response
schemas, the cohort vector grammar, the raw statistical quantities returned
in the response, calibration references from the existing cohort library,
the diagnostic-to-prompt heuristics the chatbot uses to drive iteration,
error states, and caching mechanics. Examples are included throughout.

The intended reader is anyone implementing either side of the boundary:
the frontend developer wiring the chat UI to the API, the backend developer
wrapping `pipeline.py` as endpoints, and the prompt engineer encoding the
chatbot's interpretive layer.

## Design principles

This spec is constrained by four principles, in order of priority:

1. **Simple.** Few endpoints, few keys, no invented composite scores.
2. **Flexible.** The same raw stats serve different interpretations
   depending on the user's stated intent for the cohort.
3. **Auditable.** Every quantity returned by the API is a well-defined
   statistical measure with a citation or formula. No magic-number
   thresholds bake editorial decisions into the schema.
4. **Academically defensible.** The patterns of cohort behavior identified
   so far (broadly distributed, demographically anchored, historically
   clustered) are interpretive findings per paper Section 9, not mechanical
   classifications, and they are not a closed set. New patterns may emerge
   as the library grows. They live in the LLM's prose, not in the API
   contract. See section 4 of this document for the underlying paradigm.

The most consequential implication: the API does not return a
`cohort_type` enum, a `fit_quality` enum, or any other classified label.
It returns raw statistical quantities. Classification happens in
conversation between the LLM and the user, with the LLM anchored by
calibration references from the existing cohort library (section 4).

---

## 1. Overview

### 1.1 What the endpoint does

`POST /score` takes a cohort definition (the same structural shape as an
entry in `subcultures.yaml`) and returns:

1. A `cohort_id` (content-hash, used by the frontend as a layer key).
2. A URL to a tract-level scores JSON file the frontend fetches and
   merges into the map's `scores` state.
3. A `stats` object containing raw statistical quantities computed during
   the pipeline run.

### 1.2 Latency target

Single-cohort runs should complete in under 60 seconds. The first run
for a given content hash may sit near that ceiling; subsequent identical
requests hit cache and return in under 200 ms.

### 1.3 What lives where

- **Frontend**: composes the request from the LLM's draft YAML, POSTs to
  the backend, receives the response, fetches the JSON file, merges the
  scores into existing state, and adds the cohort to `selectedIds` so
  the map renders it.
- **Backend (FastAPI)**: validates the request, computes the content
  hash, checks the marginal cache, runs the pipeline for this one
  cohort, writes `tract_scores_<hash>.json` to disk, returns the
  response.
- **LLM (Anthropic API, called from backend)**: handles the conversation
  with the user. Drafts the cohort YAML. Asks the user early on which
  cohort pattern (section 4) they imagine the group to exhibit, drawn
  from the currently-named set; the user's answer lives in conversation
  context. Receives the raw stats from `POST /score`, compares them
  against calibration references and the user's stated expectation, and
  composes the next
  message.

---

## 2. Request Schema

### 2.1 Endpoint

```
POST /score
Content-Type: application/json
```

### 2.2 Request body

```json
{
  "name": "Crocs people",
  "vibe": "comfortable shoes, don't @ me",
  "threshold": 0.5,
  "tract_marginals": [
    "B19001_009E",
    "B25024_002E"
  ],
  "vector": [
    {
      "field": "AGEP",
      "op": "range",
      "value": [25, 65],
      "weight": 1.5,
      "required": true
    },
    {
      "field": "TEN",
      "op": "in",
      "value": [1, 2],
      "weight": 1,
      "required": false
    }
  ],
  "proxy_gap": "Crocs ownership is not a census variable. The cohort relies on adult age range and owner-occupied housing as weak structural proxies; the result will be intentionally broad."
}
```

### 2.3 Field semantics

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Display name. Not used in scoring. |
| `vibe` | string | yes | The editorial flavor line. Not used in scoring. Presentation only. |
| `threshold` | float | no | Membership threshold τ in (0, 1]. Defaults to 0.5. |
| `tract_marginals` | array of strings | yes | ACS census table codes (e.g., `B19001_017E`). 1 to 6 entries recommended; more than 6 risks multicollinearity. Hard upper bound: 8. |
| `vector` | array of vector entries | yes | The weighted condition list. At least one entry must have `required: true`. |
| `proxy_gap` | string | no | Documentation of what the data can and cannot capture. Stored, not used in scoring. |

Note the deliberate absence of any `cohort_type` field. The user's
self-classification of cohort behavior lives in the chat conversation;
the pipeline runs the same way regardless of the user's stated
expectation. See section 4.

### 2.4 Vector entry schema

Each entry in `vector` must have:

```json
{
  "field": "AGEP",
  "op": "range",
  "value": [25, 65],
  "weight": 1.5,
  "required": false
}
```

| Field | Type | Notes |
|-------|------|-------|
| `field` | string | PUMS field name. Must be in the known fields list (see section 5). |
| `op` | enum | One of `eq`, `in`, `range`, `gte`, `lte`, `occupation_soc_major`, `industry_naics`. See section 5.2. |
| `value` | varies | Shape depends on `op`. See section 5.2. |
| `weight` | float | Positive, conventionally 0.5 to 5. Higher values are more strongly defining. |
| `required` | bool | Optional, defaults to false. If true, this is a hard gate; records failing it are not cohort members regardless of soft score. |

### 2.5 Hash inputs

The `cohort_id` is derived as the first 12 hex characters of the SHA-256
hash of a canonical JSON serialization of:

```
{
  "threshold": <float>,
  "tract_marginals": <sorted array of strings>,
  "vector": <vector array, normalized order and key set>
}
```

`name`, `vibe`, and `proxy_gap` are not part of the hash. Two requests
with identical computational inputs but different display text return
the same `cohort_id` and share the cached `tract_scores_<hash>.json`
file. The backend stores the most recent `name` and `vibe` it has seen
for a hash, but this metadata is descriptive only.

Normalization rules for hashing:

- `vector` entries are sorted by `(field, op)` then by stringified `value`.
- Within each entry, keys are emitted in alphabetical order.
- `required: false` is treated as absent (default) for normalization.
- `weight` is rounded to two decimal places.
- `tract_marginals` is sorted lexicographically and deduplicated.

This ensures cosmetic differences in request shape do not produce
different cache keys.

---

## 3. Response Schema

### 3.1 Success response (200 OK)

```json
{
  "cohort_id": "a1b2c3d4e5f6",
  "tract_scores_url": "/data/tract_scores_a1b2c3d4e5f6.json",
  "stats": {
    "weighted_member_count": 287400,
    "weighted_gate_pass": 312000,
    "mean_fit_per_member": 0.74,
    "concentration_index": 0.42,
    "n_pumas_nonzero": 268,
    "n_pumas_total": 281,
    "r_squared": 0.58,
    "loocv_r_squared": 0.56,
    "morans_i_residual": 0.12,
    "morans_i_z_score": 3.8,
    "morans_i_p_value": 0.00014,
    "residual_std": 132.4,
    "lambda_chosen": 10.0,
    "fay_herriot_median_gamma": 0.93,
    "feature_names": ["population", "B19001_009E", "B25024_002E"],
    "feature_coefs": [0.0, 286.3, 41.2],
    "marginal_reliability_summary": "B19001_009E: 89% caution, 8% unreliable; B25024_002E: 36% caution, 5% unreliable"
  },
  "cache_status": "miss",
  "elapsed_ms": 38420
}
```

### 3.2 Field semantics

**Top-level**

| Field | Type | Notes |
|-------|------|-------|
| `cohort_id` | string | Content hash, 12 hex characters. Use as the layer key on the frontend. |
| `tract_scores_url` | string | Path to the cohort's tract-level scores JSON. Fetch it and merge into the map's scores state. |
| `stats` | object | Raw statistical quantities from the pipeline run. See 3.3. |
| `cache_status` | enum | `hit` if returned from cache (no pipeline run), `miss` if freshly computed. |
| `elapsed_ms` | int | Wall-clock time from request received to response sent. For monitoring. |

### 3.3 stats object

Every field is a raw statistical quantity with a defined formula or
standard reference. There are no derived enums or composite scores.
The LLM's system prompt instructs which fields are appropriate to
surface in conversational prose (population count, qualitative
descriptions of shape) versus which are used internally for
interpretation but never quoted (R², Moran's I, etc.).

| Field | Type | Definition | Reference |
|-------|------|------------|-----------|
| `weighted_member_count` | int | PWGTP-weighted count of PUMS records passing all hard gates and clearing threshold. The population estimate. | Standard SAE population total, Rao and Molina 2015 §1.3. |
| `weighted_gate_pass` | int | PWGTP-weighted count of records passing all hard gates (before threshold check). | Same. |
| `mean_fit_per_member` | float in [0, 1] | Average soft-score among cohort members, normalized by the cohort vector's maximum possible weight. | Project-defined diagnostic, METHODOLOGY.md §6. |
| `concentration_index` | float in [0, 1] | Gini coefficient of EBLUP PUMA estimates. 0 = perfectly uniform across PUMAs, 1 = all weight in one PUMA. | Gini 1912; standard inequality measure. See section 6.1 for formula. |
| `n_pumas_nonzero` | int | Count of PUMAs with EBLUP estimate strictly above zero. 281 total in CA. | |
| `n_pumas_total` | int | 281 for CA. Included for reference. | |
| `r_squared` | float | In-sample R² of the ridge-NNLS fit at the PUMA level. | Standard. |
| `loocv_r_squared` | float | Leave-one-out cross-validation R². The honest fit indicator. | Standard cross-validation; Hastie, Tibshirani, and Friedman 2009 §7.10. |
| `morans_i_residual` | float | Spatial autocorrelation in regression residuals under queen contiguity. | Moran 1950; Cliff and Ord 1981. |
| `morans_i_z_score` | float | Standardized Moran's I. | Same. |
| `morans_i_p_value` | float | Two-sided p-value for spatial autocorrelation. | Same. |
| `residual_std` | float | Standard deviation of regression residuals. | Standard. |
| `lambda_chosen` | float | Ridge penalty selected via LOOCV grid. | Hoerl and Kennard 1970. |
| `fay_herriot_median_gamma` | float in [0, 1] | Median shrinkage weight across PUMAs. High γ = PUMA direct estimates dominate; low γ = model predictions dominate. | Fay and Herriot 1979. |
| `feature_names` | array of strings | Feature column names including population baseline. | |
| `feature_coefs` | array of floats | Back-transformed coefficients (z-score scale undone). | |
| `marginal_reliability_summary` | string | Human-readable summary of tract-level CV diagnostics for the chosen marginals (caution band ≥ 12%, unreliable band ≥ 40%). | Census Bureau 2020 ch. 7; Spielman and Singleton 2015. |

### 3.4 Tract scores JSON file (`tract_scores_<hash>.json`)

The file at `tract_scores_url` has the same nested shape as the existing
batch pipeline's output, with a single cohort inside. This means the
frontend merge logic that already handles multi-cohort scores works
unchanged.

```json
{
  "06037103100": { "a1b2c3d4e5f6": 1247.3 },
  "06037103200": { "a1b2c3d4e5f6": 982.1 },
  "06037103300": { "a1b2c3d4e5f6": 1411.8 }
}
```

Outer keys are 11-character census tract GEOIDs. Inner objects have a
single key: the cohort hash. Values are EBLUP estimates after
MOE-weighted raking to tract level. Numeric type is float.

Tracts with zero or undefined cohort presence are omitted from the file
(rather than included with a zero value) to keep the file small.

### 3.5 File lifecycle

`tract_scores_<hash>.json` files are written to disk on cohort creation
and persist indefinitely. The content-hash key makes accidental
duplication impossible. Future "gallery" features rely on this
persistence.

A separate `cohorts_index.json` file maintained by the backend stores
metadata for every cohort ever created: hash, name, vibe, stats
summary, creation timestamp. This is the gallery index. Not part of
the `POST /score` contract but worth noting here.

---

## 4. Patterns as Interpretive Frames

### 4.0 The paradigm: calibration as finding

The patterns of cohort behavior surfaced by this project (so far:
broadly distributed, demographically anchored, historically clustered)
are **findings about the relationship between the cohort's editorial
intent and the demographic record**, not pre-defined classifications.
They are derived from the statistical signatures of authentically
authored cohorts; they are not designed first and then matched against
cohorts.

This is the project's **calibration-as-finding paradigm**: the LLM's
interpretive vocabulary grows out of the cohort library, not out of
analytic ambition. Three implications follow:

1. **The currently named patterns are not a closed set.** As new
   editorial cohorts are authored, the library may reveal additional
   patterns, or refine the boundaries between existing ones. The
   pipeline does not assume the count is three.
2. **No cohort exists solely to populate a pattern slot.** Every
   cohort in the library is a positioned editorial contribution. The
   calibration value of a cohort is a side effect of its editorial
   authorship, never the reason for it.
3. **The calibration table is a living artifact.** It regenerates
   from the latest batch run and reflects whatever the library
   currently contains.

The methodology aligns with paper Section 9 directly:

> "The diagnostics must be read in conversation with the archetype's
> editorial intent rather than as standalone pass-fail tests. A high
> residual Moran's I is a problem when the archetype is supposed to
> be broadly distributed but a finding when the archetype is supposed
> to be culturally clustered." (Section 9)

This commitment shapes the API contract. The API does not return a
`cohort_type` enum because the same raw stats can support different
interpretive conclusions depending on what the cohort author imagined.
Pre-defining thresholds for the patterns would contradict the paper's
central methodological position by treating diagnostics as mechanical
pass/fail rather than as evidence to be interpreted.

### 4.1 How patterns appear in the conversation

The LLM asks the user early in the chat which of the currently-named
patterns they imagine the cohort to exhibit, or whether they expect a
pattern not yet named in the library. The user's answer is stored in
conversation context, not sent to the backend. After the pipeline
returns raw stats, the LLM applies the calibration references in
section 4.2 and the user's stated expectation to compose its next
message.

When the user is uncertain ("not sure" / "no opinion"), the LLM falls
back to descriptive language anchored against the calibration
references without invoking the user's expectation.

### 4.2 Calibration references from the existing cohort library

The LLM's system prompt should include the table below. These are
real cohort outputs from prior pipeline runs that ship with the
project, used as anchors for qualitative interpretation. The table
should be regenerated whenever the cohort library or the pipeline
changes; values are not constants of the universe.

| Existing cohort | Author's stated pattern | concentration_index | loocv_r² | morans_i_residual | morans_i_p | Notes |
|-----------------|-------------------------|---------------------|----------|-------------------|------------|-------|
| crumbl_cookie_couple | broadly distributed | 0.32 | 0.47 | 0.48 | < 0.001 | Suburban diffuse pattern matched author's intent. |
| bilingual_baddie | demographically anchored | 0.42 | 0.86 | 0.25 | < 0.001 | Sharp on language marginals; clean fit. |
| queer_leftist | demographically anchored | 0.45 | 0.67 | 0.04 | 0.17 | Cleanest fit in the library. |
| teen_boy | demographically anchored | 0.40 | 0.56 | 0.24 | < 0.001 | Some unexplained spatial structure remaining. |
| hill_people | historically clustered | 0.55 | 0.77 | 0.26 | < 0.001 | Tight on rural-housing marginals. |
| crazy_person | historically clustered | 0.50 | 0.61 | 0.09 | 0.006 | Tenderloin/Skid-Row concentration. |
| married_gays | historically clustered | 0.45 | 0.20 | 0.12 | < 0.001 | Low R² is itself the finding: marginals can't reach the historical enclaves. |

Numbers are illustrative anchors drawn from the most recent batch run;
the backend should regenerate this table from the latest results when
the LLM's system prompt is composed. The table is not a normative grid
but a positioned reading of where the existing library sits.

### 4.3 What the LLM does with these references

The LLM uses the calibration references to *describe* a new cohort's
stats in plain language, then *compare* that description to the user's
stated expectation. Some illustrative readings, expressed in natural
language rather than threshold rules:

- "The new cohort's concentration_index is similar to bilingual_baddie
  and queer_leftist; it sits in the demographically-anchored range the
  existing library demonstrates."
- "loocv_r² is lower than every existing cohort except married_gays;
  the marginals you picked don't predict this cohort's geography
  strongly. If you said historically clustered, this is the
  married-gays pattern (low R² is the finding). If you said
  demographically anchored, you might try different marginals."
- "Moran's I residual is significant and positive; there's a
  geographic pattern the marginals aren't catching, similar to
  hill_people and bilingual_baddie. If you have a region in mind for
  this cohort, naming it could improve the fit."

The chatbot prose never asserts that a cohort *is* a member of a named
pattern. It describes where the stats sit relative to existing anchors
and asks the user whether the result matches their picture. This
preserves the paper's commitment to the user's positioned imagination
as the verification criterion. It also leaves room for the chatbot to
recognize when a cohort sits outside the currently-named patterns:
that recognition is data the next library revision can act on.

---

## 5. Vector Grammar

### 5.1 Known fields

The `field` value in a vector entry must be one of the loaded PUMS
variables. The current set is documented separately in
`docs/pums_field_dictionary.md` (TODO). Backend validation rejects
unknown fields with a 422 error (see section 8).

Key field categories:

- **Person-level** (PERSON_VARS): AGEP, SEX, MAR, ESR, ESP, OCCP, INDP,
  COW, RELSHIPP, RAC1P, HISP, NATIVITY, LANX, LANP, ENG, SCHL, SCH,
  PINCP, WAGP, WKHP, WKL, POVPIP, DIS, DREM, DPHY, DEAR, DEYE, DOUT,
  DDRS, PUBCOV, HINS1, SSP, SSIP, PAP, MIG, FER, MIL, JWTRNS, plus
  derived SAME_SEX.
- **Household-level** (HOUSING_VARS): TEN, HHT, HHL, MV, VEH, HINCP,
  BDSP, BLD, VALP, HFL, YRBLT, ACR, AGS, TEL, BROADBND, PLM, LAPTOP,
  FS, PARTNER, MULTG, HUPAOC, HHLDRRAC1P.

Household-level fields are inherited onto person records via SERIALNO
join during PUMS load, so they are usable on any vector entry
regardless of the cohort's focal record type.

### 5.2 Operators

| Op | Value shape | Semantics | Example |
|----|-------------|-----------|---------|
| `eq` | scalar int or string | Field equals value | `{ "op": "eq", "value": 1 }` |
| `in` | array of scalars | Field is one of the listed values | `{ "op": "in", "value": [1, 2, 3] }` |
| `range` | 2-element array `[min, max]` | Inclusive numeric range | `{ "op": "range", "value": [25, 65] }` |
| `gte` | scalar number | Field is greater than or equal | `{ "op": "gte", "value": 80000 }` |
| `lte` | scalar number | Field is less than or equal | `{ "op": "lte", "value": 17 }` |
| `occupation_soc_major` | array of SOC major-group codes (int) | OCCP belongs to one of these SOC majors (computed via SOC mapping) | `{ "op": "occupation_soc_major", "value": [27, 25] }` |
| `industry_naics` | array of NAICS supersector codes (int) | INDP belongs to one of these supersectors | `{ "op": "industry_naics", "value": [51, 54, 61] }` |

For `range`, the values are inclusive on both ends. For `gte` and
`lte`, inclusive. Records with missing or NA values for the named
field do not satisfy any condition; soft conditions return 0 for them,
required gates exclude them.

### 5.3 Hard gates vs soft signals

Conditions with `required: true` are hard gates: records failing them
are not cohort members. This is the structural filter.

Conditions with `required: false` (or absent) are soft signals: records
that satisfy them get the condition's weight added to their soft
score. Records' weighted soft scores are normalized by the sum of soft
weights, producing a value in [0, 1]. Records whose normalized soft
score is below `threshold` are excluded.

A record is a member if and only if it passes all hard gates and
clears the threshold.

### 5.4 Validation rules

The backend rejects requests where:

- `vector` is empty (HTTP 422).
- No entries have `required: true`. A cohort with no hard gates would
  admit nearly everyone weighted by soft fit; the project convention
  is that every cohort has at least one identity gate (HTTP 422, code
  `no_required_gate`).
- Any `field` is not in the known fields list (HTTP 422).
- Any `op` is not in the operators list (HTTP 422).
- Any `value` has the wrong shape for its `op` (HTTP 422).
- `threshold` is outside (0, 1] (HTTP 422).
- `tract_marginals` is empty or has more than 8 entries (HTTP 422; 8
  is a hard upper bound to prevent multicollinearity catastrophes).

---

## 6. Stats Derivations

This section gives the formulas for the two stats that are not standard
out-of-the-box statistical quantities. Everything else in the `stats`
object follows its referenced literature (Fay and Herriot 1979 for the
EBLUP, Moran 1950 for Moran's I, Hoerl and Kennard 1970 for ridge,
Wolter 2007 for SDR variance).

### 6.1 concentration_index (Gini coefficient)

Computed on the EBLUP PUMA estimates after Fay-Herriot shrinkage but
before raking to tracts. Formula (Gini 1912; standard expression):

```
Sort PUMA estimates x_1, ..., x_n in ascending order.
G = (2 * Σ_{i=1..n} (i * x_i)) / (n * Σ_{i=1..n} x_i) - (n + 1) / n
```

Range: 0 (uniform across all 281 PUMAs) to slightly under 1 (all
weight in one PUMA). If all PUMA estimates are zero or all equal,
return 0.

The Gini was chosen because it is a single number with a well-known
interpretation, has been the workhorse inequality measure in spatial
and economic distribution analysis for over a century, and its range
is bounded. Alternatives considered: Theil index (decomposable but
less intuitive), HHI (sensitive to count of bins), top-decile share
(simpler but ignores the full distribution). Gini was selected for
interpretability.

### 6.2 mean_fit_per_member

Already computed in the existing pipeline as:

```
mean_fit_per_member = weighted_soft_total / weighted_member_count / total_soft_weight
```

where `total_soft_weight` is the sum of weights across the cohort's
soft (non-required) conditions. Returns the fraction of the cohort
vector's soft weight that the average member satisfies. Closer to 1
means members fit the vector tightly; closer to `threshold` means
members barely qualify.

---

## 7. Diagnostic-to-Prompt Heuristics

The chatbot reads the response and decides what to say next. The
guidance below is a heuristic checklist, not a deterministic rule
table. The LLM applies it with the user's stated expectation (held in
chat context) and the calibration references from section 4.2 as the
interpretive substrate.

The four operating modes the chatbot should be capable of:

### 7.1 Acknowledge and step back

If no diagnostic raises a concern, the chatbot acknowledges and waits.

> Built. About 287,000 Californians match this cohort. The dots are now
> on the map. Want to tighten anything?

The chatbot does not narrate technical stats unless asked. This is the
common case for cohorts that produce a reasonable population count, a
fit in the same ballpark as existing library cohorts, and no surprising
spatial pattern in residuals.

### 7.2 Size-driven prompts

The LLM should propose a tightening or loosening question when the
weighted member count is outside the comfortable middle range.
Reference points for "comfortable middle":

- Below 5,000: probably an over-gated cohort; surface the rarity.
- Below 50,000: small cohort; ask whether smallness is the intent.
- Above 5,000,000: large slice of California; ask whether a tightening
  gate would help.
- Above 12,000,000: most of California's adult population; almost
  certainly needs a gate.

Calibration anchor: existing cohorts range from approximately 120,000
(crazy_person) to 1,000,000 (bilingual_baddie). The library's "small"
is around the high tens of thousands; the library's "large" is around
the high hundreds of thousands.

Example phrasing:

> Only about 31,000 people match. Want to loosen something, or is this
> meant to be a small group?

### 7.3 Fit-driven prompts

When `loocv_r_squared` is materially lower than the calibration
references for the user's stated pattern, OR when `morans_i_p_value`
is significant with high `morans_i_residual` (meaning unexplained
spatial structure), the chatbot proposes a change.

The phrasing differs based on the user's stated expectation:

- If the user said *demographically anchored* and the stats look like
  the married_gays row (low R², high Moran's I), the prompt should
  surface the possibility that the user's intent is actually
  historically clustered, framed as a question.
- If the user said *historically clustered* and the stats look like
  hill_people (high R², high Moran's I), affirm that the stats match
  the pattern.
- If the user said *broadly distributed* and the stats look like
  crumbl_cookie_couple (low concentration, high R² for population),
  affirm.

Example phrasing for low fit:

> The geography looks noisy. For comparison, the existing library
> cohorts run loocv_r² between 0.20 and 0.86. Yours is at 0.25. Want
> to anchor on a different census signal: income, language at home,
> housing type, occupation?

### 7.4 Concentration-driven prompts (the calibration loop)

When the cohort's `concentration_index` sits clearly outside the range
the user's stated expectation predicts, surface the mismatch as a
calibrative question, never as a correction.

Reference: existing cohorts' `concentration_index` ranges from
approximately 0.32 (crumbl_cookie_couple) to 0.55 (hill_people).
"Pretty broadly spread" reads as < 0.35 in this library; "pretty tightly
clustered" as > 0.55.

Example phrasing when a user said "broadly distributed" but the cohort
came out tightly concentrated:

> These cluster more than I'd expect for a broadly distributed cohort.
> The map looks more like the hill_people pattern. Does that match the
> picture in your head, or do you want to broaden?

Example for the inverse direction:

> Pretty spread out for an anchored cohort. Want to add an anchor: an
> age range, an occupation, a region?

### 7.5 Trigger composition and priority

The LLM evaluates all four operating modes against the response and
composes one prompt per turn using the most informative trigger. If
multiple concerns are real, the order of priority is:

1. Extreme size (under 5,000 or over 12 million is louder than anything else).
2. Fit mismatch with user's stated pattern.
3. Concentration mismatch with user's stated pattern.
4. Moderate size signals.

When the user is uncertain about the cohort pattern, the LLM does not
fire mismatch triggers; it offers a descriptive reading of the stats
anchored against the calibration table and asks the user what they
make of it.

---

## 8. Error States

### 8.1 4xx validation errors

Returned synchronously before any pipeline work. Body shape:

```json
{
  "error": "validation_error",
  "code": "unknown_field",
  "message": "Field 'AGPE' is not in the known PUMS fields list. Did you mean 'AGEP'?",
  "field_path": "vector[2].field"
}
```

Error codes:

| HTTP | Code | Trigger |
|------|------|---------|
| 422 | `unknown_field` | A vector entry references a field not in known fields. |
| 422 | `unknown_op` | A vector entry uses an unsupported operator. |
| 422 | `bad_value_shape` | The `value` does not match the shape required by `op`. |
| 422 | `no_vector` | The `vector` array is empty. |
| 422 | `no_required_gate` | No entries have `required: true`. |
| 422 | `bad_threshold` | Threshold is outside (0, 1]. |
| 422 | `bad_marginal_count` | Fewer than 1 or more than 8 tract marginals. |
| 422 | `unknown_marginal` | A tract marginal code does not exist in ACS. |

The `message` field is human-readable and may be surfaced by the LLM
to the user. The `code` field is machine-readable for client-side
handling.

### 8.2 5xx runtime errors

Returned after partial pipeline execution.

| HTTP | Code | Trigger | Cacheable? |
|------|------|---------|------------|
| 502 | `marginal_fetch_failed` | Census API failed or timed out. | No |
| 500 | `pipeline_failure` | Unhandled exception during scoring or model fit. | No |
| 504 | `pipeline_timeout` | Pipeline exceeded 90 seconds wall-clock. | No |

### 8.3 Special case: zero members

A request that validates cleanly but yields zero cohort members
returns HTTP 200 with `weighted_member_count: 0`. The chatbot
recognizes this case from the size guidance in section 7.2 and prompts
for a loosening. This is not an error; it is a real and useful
signal.

In this case, `concentration_index` is set to 0 by convention (since
an empty cohort has nothing to distribute).

---

## 9. Caching Mechanics

### 9.1 Cache layers

Three caches sit on the backend:

1. **Cohort result cache** (disk). Key: content hash of cohort
   definition. Value: the `tract_scores_<hash>.json` file plus a
   sidecar metadata file with the response object. On cache hit, the
   backend returns the sidecar verbatim with `cache_status: "hit"`. No
   pipeline work.

2. **Marginal cache** (in-process dict, optionally backed by Redis or
   sqlite). Key: ACS variable code (e.g., `B19001_017E`). Value:
   per-tract estimates and MOEs. Marginals are reused across cohorts,
   so this cache is high-hit-rate. TTL: refresh on each ACS vintage
   release.

3. **PUMS parquet** (in-process pandas DataFrame). Loaded once at
   service startup. Never evicted while the process is alive.

### 9.2 Cache hit response

When a content hash matches an existing cohort, the backend returns
the stored response with `cache_status: "hit"` and `elapsed_ms`
reflecting only the cache lookup (typically under 50 ms). The
`tract_scores_url` points at the existing file on disk; no rewrite
happens.

### 9.3 Cache invalidation

The cohort result cache is content-addressable; there is no need to
invalidate. If the pipeline code changes (new methodology, bug fix),
the operator runs a manual invalidation script that clears all cached
files and forces recomputation on next request. This is rare.

The marginal cache invalidates on ACS vintage release. The backend
tracks the loaded vintage and refuses requests if the configured
vintage differs from the cached marginals.

### 9.4 Disk usage

Each `tract_scores_<hash>.json` file is approximately 50-200 KB for a
typical cohort. At 1000 unique cohorts, disk usage is roughly 100 MB.
No practical concern.

---

## 10. Examples

### 10.1 Minimal valid cohort

```json
{
  "name": "Adults",
  "vibe": "you are an adult",
  "tract_marginals": ["B01001_001E"],
  "vector": [
    { "field": "AGEP", "op": "gte", "value": 18, "weight": 1, "required": true }
  ]
}
```

Produces a cohort of roughly 30 million weighted members. The chatbot
fires the over-12-million size signal and asks the user to add a gate.

### 10.2 Identity cohort

```json
{
  "name": "Bus driver",
  "vibe": "drives the bus. takes the bus home.",
  "tract_marginals": ["B08301_010E", "B25024_005E"],
  "vector": [
    { "field": "AGEP", "op": "range", "value": [22, 65], "weight": 1.5, "required": true },
    { "field": "OCCP", "op": "occupation_soc_major", "value": [53], "weight": 3, "required": true },
    { "field": "INDP", "op": "industry_naics", "value": [48], "weight": 1.5, "required": true },
    { "field": "WKHP", "op": "gte", "value": 30, "weight": 1, "required": true },
    { "field": "TEN", "op": "eq", "value": 3, "weight": 1.5 },
    { "field": "VEH", "op": "lte", "value": 1, "weight": 1 },
    { "field": "JWTRNS", "op": "in", "value": [3, 4, 5, 6, 7, 11], "weight": 0.5 }
  ],
  "proxy_gap": "Occupation gate captures transportation-and-material-moving SOC. Soft signals for being a transit user when off-duty: rents, no car, takes transit to work."
}
```

The LLM would compare the resulting stats against the calibration
references; this cohort likely lands near bilingual_baddie's profile
(demographically anchored on occupation).

### 10.3 Validation failure

Request:
```json
{
  "name": "Bad cohort",
  "vibe": "...",
  "tract_marginals": ["B01001_001E"],
  "vector": [
    { "field": "AGPE", "op": "gte", "value": 18, "weight": 1, "required": true }
  ]
}
```

Response (HTTP 422):
```json
{
  "error": "validation_error",
  "code": "unknown_field",
  "message": "Field 'AGPE' is not in the known PUMS fields list. Did you mean 'AGEP'?",
  "field_path": "vector[0].field"
}
```

### 10.4 Cache hit

A second POST with the same computational inputs (different `name` or
`vibe` is allowed):

```json
{
  "cohort_id": "a1b2c3d4e5f6",
  "tract_scores_url": "/data/tract_scores_a1b2c3d4e5f6.json",
  "stats": { /* same as the cached miss response */ },
  "cache_status": "hit",
  "elapsed_ms": 38
}
```

---

## 11. Open questions

Deferred until the schema is in use.

1. **Authentication.** None proposed for v1. If abuse appears, add a
   rate-limit per IP and a per-session API key.
2. **Cohort editing.** Currently every edit creates a new cohort_id
   (different hash). Should there be a notion of "this cohort is a
   revision of that one" for the gallery? Probably yes, via a separate
   `parent_id` field that does not affect the hash.
3. **User-supplied marginals.** The chatbot proposes tract marginals
   from a curated set; should the user be able to specify arbitrary
   ACS table codes? Probably yes, but with a soft warning when
   reliability is poor.
4. **Sharing.** `tract_scores_<hash>.json` is publicly fetchable. Is
   the underlying cohort definition also publicly readable via the
   gallery? Almost certainly yes for an artistic tool, but worth
   confirming.
5. **Multi-cohort comparison.** Should `POST /score` support a batch
   mode for the chatbot to compute several variations at once during
   iteration? Possible v2 feature.
6. **Calibration table refresh.** Section 4.2's table is a snapshot.
   How and when does it regenerate when the library or pipeline
   changes? Probably emit it as a build artifact alongside
   `tract_scores.json` on every full batch run.

---

## 12. References

- Census Bureau. *Understanding and Using American Community Survey
  Data: What All Data Users Need to Know*. U.S. Census Bureau, 2020.
- Cliff, A. D., and Ord, J. K. *Spatial Processes: Models &
  Applications*. Pion, 1981.
- Fay, R. E., and Herriot, R. A. "Estimates of Income for Small
  Places: An Application of James-Stein Procedures to Census Data."
  *Journal of the American Statistical Association*, 74(366):269–277,
  1979.
- Gini, C. *Variabilità e mutabilità*. Bologna: C. Cuppini, 1912.
- Hastie, T., Tibshirani, R., and Friedman, J. *The Elements of
  Statistical Learning*. 2nd ed. Springer, 2009.
- Hoerl, A. E., and Kennard, R. W. "Ridge Regression: Biased Estimation
  for Nonorthogonal Problems." *Technometrics*, 12(1):55–67, 1970.
- Moran, P. A. P. "Notes on Continuous Stochastic Phenomena."
  *Biometrika*, 37(1–2):17–23, 1950.
- Rao, J. N. K., and Molina, I. *Small Area Estimation*. 2nd ed. Wiley,
  2015.
- Spielman, S. E., and Singleton, A. "Studying Neighborhoods Using
  Uncertain Data from the American Community Survey: A Contextual
  Approach." *Annals of the Association of American Geographers*,
  105(5):1003–1025, 2015.
- Wolter, K. M. *Introduction to Variance Estimation*. 2nd ed.
  Springer, 2007.

Paper-internal cross-reference: this spec aligns with the
*Where Real Californians Live* report, particularly Section 9
("Findings") on the patterns taxonomy and Section 7
("Geographic Distribution: Fay–Herriot Small-Area Estimation") on the
statistical pipeline that produces the stats returned by this API.
