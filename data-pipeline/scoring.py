"""Per-record cohort scoring and PUMA aggregation.

Owns the editorial layer of the pipeline: how individual PUMS person
records get evaluated against a cohort's trait vector, gated by
required conditions, summed into a soft fit score, thresholded into a
binary membership indicator, and aggregated up to PUMAs with
successive-difference replicate-weight variance. Also parses cohort
definitions to extract the ACS tract-marginal codes the SAE step will
need.

Methodology references live in METHODOLOGY.md ("Scoring", "PUMA
aggregation", "SDR variance") and in each function's docstring. The
numerical primitives are unchanged from when this code lived in
pipeline.py; this module is purely a reorganization.
"""

from __future__ import annotations

import pandas as pd

# Replicate-weight count lives with the field catalog loader in data_prep;
# imported here for aggregate_to_puma_variance's SDR computation.
from data_prep import N_REPLICATE_WEIGHTS


# Default membership threshold τ. A PUMS record counts as a cohort member iff
# every `required: true` condition in the trait vector passes AND the soft
# similarity score is at or above this threshold. Override per cohort by
# adding `threshold:` to the cohort entry in web/lib/library.json. See
# METHODOLOGY.md "Scoring" for rationale.
DEFAULT_MEMBERSHIP_THRESHOLD: float = 0.5


# Track unknown fields seen during scoring so we warn once per field per run
# rather than spamming for every cohort that uses the same typo.
_UNKNOWN_FIELDS_WARNED: set[str] = set()

def _eval_condition(df: pd.DataFrame, cond: dict) -> pd.Series:
    """Returns a 0..1 Series indicating how well each row satisfies the condition.

    If the named field is not in the DataFrame, returns all zeros (so the
    cohort still scores) but prints a warning once per unique missing field.
    Common cause: a typo in web/lib/library.json (e.g., AGEPP for AGEP).
    """
    if cond.get("computed") == "modal":
        # Special-cased upstream.
        return pd.Series(0.0, index=df.index)
    field = cond["field"]
    if field not in df.columns:
        if field not in _UNKNOWN_FIELDS_WARNED:
            print(
                f"[warn] field '{field}' not in PUMS DataFrame columns. "
                "All conditions referencing this field will score 0. "
                "Check spelling in web/lib/library.json against PERSON_VARS / HOUSING_VARS."
            )
            _UNKNOWN_FIELDS_WARNED.add(field)
        return pd.Series(0.0, index=df.index)
    series = df[field]
    op = cond["op"]
    value = cond["value"]

    if op == "eq":
        return (series == value).astype(float)
    if op == "in":
        return series.isin(value).astype(float)
    if op == "range":
        lo, hi = value
        return ((series >= lo) & (series <= hi)).astype(float)
    if op == "gte":
        return (series >= value).astype(float)
    if op == "lte":
        return (series <= value).astype(float)
    if op == "industry_naics":
        # INDP is a numeric code; map to NAICS sector by leading digit ranges.
        # Simplified: keep a sector lookup. For v0 we approximate by code range.
        sectors_to_codes = {
            11: range(170, 290),    # agriculture
            51: range(6470, 6790),  # information
            54: range(7270, 7790),  # professional services
            61: range(7860, 7890),  # education
            62: range(7890, 8470),  # health care
            71: range(8560, 8690),  # arts/recreation
            72: range(8680, 8980),  # accommodation/food
        }
        wanted = set()
        for sec in value:
            wanted.update(sectors_to_codes.get(sec, []))
        return series.isin(wanted).astype(float)
    if op == "occupation_soc_major":
        # OCCP codes follow a 4-digit pattern roughly aligned with SOC major groups.
        # 15-XXXX (computer/math): roughly 1005-1240. 17-XXXX (engineering): 1300-1540. etc.
        # For v0, use a coarse mapping: integer divide by 100 ~ major group.
        major = (series // 100).astype("Int64")
        return major.isin(value).astype(float)
    if op == "occupation_soc_minor":
        # Treat value as a list of 4-digit prefix codes.
        prefix_match = series.astype("Int64").isin(value)
        return prefix_match.astype(float)
    if op == "spanish":
        # LANP code 1200 = Spanish in PUMS.
        return (series == 1200).astype(float)
    if op == "percentile_gte":
        threshold = df[field].quantile(value / 100.0)
        return (series >= threshold).astype(float)
    raise ValueError(f"Unknown operator: {op}")


def score_subculture(df: pd.DataFrame, sub: dict) -> tuple[pd.Series, pd.Series]:
    """Compute the gate indicator and the soft similarity score per record.

    Returns
    -------
    gate : pd.Series[bool]
        True if every `required: true` condition passes for the record.
    fit_score : pd.Series[float]
        Weighted soft similarity in [0, 1]. Zero for records whose gates
        fail. The numerator sums `weight × match` over every condition
        (required and soft); the denominator is the sum of weights, so the
        score lies in [0, 1] for any gate-passing record.

    Membership is then derived elsewhere via `compute_membership()`, which
    applies the cohort's threshold τ to the fit score. See METHODOLOGY.md
    "Scoring" for the membership rule.
    """
    gate = pd.Series(True, index=df.index)
    score = pd.Series(0.0, index=df.index)
    weight_total = 0.0

    for cond in sub["vector"]:
        weight = cond.get("weight", 1.0)
        match = _eval_condition(df, cond)
        if cond.get("required"):
            gate &= match.astype(bool)
        score += weight * match
        weight_total += weight

    if weight_total == 0:
        return gate, pd.Series(0.0, index=df.index)
    fit_score = (score / weight_total).where(gate, 0.0)
    return gate, fit_score


def compute_membership(
    gate: pd.Series, fit_score: pd.Series, threshold: float
) -> pd.Series:
    """Binary cohort membership indicator per record.

    A record counts as a cohort member iff (a) every `required: true`
    condition passes (gate = True) AND (b) the soft fit score is at or
    above threshold. Returned as float (0.0 / 1.0) for compatibility with
    downstream PWGTP-weighted aggregation.
    """
    return (gate & (fit_score >= threshold)).astype(float)


def aggregate_to_puma(df: pd.DataFrame, indicators: dict[str, pd.Series]) -> dict:
    """Weight per-record indicator series by person weight (PWGTP), sum per
    PUMA, and return:
        { puma_code: { subculture_id: weighted_count } }

    With membership as the input indicator, the output is the weighted
    population count of cohort members per PUMA, a well-defined population
    total. The function also handles continuous indicators (e.g., the soft
    fit score) for secondary-diagnostic aggregation.
    """
    out: dict[str, dict[str, float]] = {}
    for sub_id, indicator in indicators.items():
        weighted = indicator * df["PWGTP"]
        per_puma = weighted.groupby(df["PUMA"]).sum()
        for puma, val in per_puma.items():
            out.setdefault(str(puma), {})[sub_id] = round(float(val), 1)
    return out


def aggregate_to_puma_variance(
    df: pd.DataFrame, indicators: dict[str, pd.Series]
) -> dict[str, dict[str, float]]:
    """Compute the sampling variance of each PUMA-level cohort estimate via
    the Census-published successive-difference replication (SDR) formula:

        Var(θ̂) = (4/80) · Σ_r (θ̂_r − θ̂)²

    where θ̂ uses the main weight PWGTP and θ̂_r uses replicate weight PWGTPr.
    Reference: Wolter 2007, *Introduction to Variance Estimation*, 2nd ed.,
    Springer, §3.7; Census Bureau, *PUMS Accuracy of the Data* (2023).

    With binary cohort membership indicators as input, this is the SDR
    variance of a population total (count of cohort members in each PUMA),
    the canonical use case for the formula.

    Returns: { puma_code: { subculture_id: sampling_variance_of_count } }.
    """
    if "PWGTP1" not in df.columns:
        # Replicate weights weren't loaded; cannot estimate sampling variance.
        return {}

    rep_cols = [f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1)]
    rep_cols = [c for c in rep_cols if c in df.columns]
    if len(rep_cols) < 4:
        return {}

    out: dict[str, dict[str, float]] = {}
    puma_index = df["PUMA"].astype(str)

    for sub_id, indicator in indicators.items():
        # Main estimate per PUMA (count of members under PWGTP).
        main_per_puma = (indicator * df["PWGTP"]).groupby(puma_index).sum()
        # 80 replicate estimates per PUMA.
        rep_per_puma = pd.DataFrame(index=main_per_puma.index)
        for r_col in rep_cols:
            rep_per_puma[r_col] = (indicator * df[r_col]).groupby(puma_index).sum()
        # SDR variance with finite-population correction factor 4/80.
        squared_dev = rep_per_puma.subtract(main_per_puma, axis=0).pow(2)
        var_per_puma = (4.0 / len(rep_cols)) * squared_dev.sum(axis=1)
        for puma, val in var_per_puma.items():
            out.setdefault(str(puma), {})[sub_id] = float(val)
    return out


