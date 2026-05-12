"""Single-cohort scoring service.

Holds the expensive-to-load pipeline state (PUMS DataFrame, tract<->PUMA
crosswalk, tract population marginal, spatial weights, PUMA centroids,
marginal cache) in process memory across requests, and exposes
``score_one_cohort()`` which runs the full pipeline for one cohort
definition end-to-end.

This module is imported by ``server.py`` (FastAPI) and is also
importable directly for testing or scripted single-cohort runs.

Design choices documented in ``docs/cohort_api_spec.md``.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Re-use the existing pipeline functions verbatim. Nothing in pipeline.py
# needs to change for the service to work; everything below is a thin
# wrapper that calls into pipeline.py with the right arguments.
from pipeline import (
    CACHE,
    DEFAULT_MEMBERSHIP_THRESHOLD,
    TractMarginal,
    _process_one_cohort_for_tracts,
    aggregate_to_puma,
    aggregate_to_puma_variance,
    build_puma_centroids,
    build_puma_queen_neighbors,
    compute_membership,
    fetch_acs_tract_marginal,
    fetch_pums,
    fetch_pumas_geojson,
    fetch_tract_puma_crosswalk,
    parse_marginal_specs,
    score_subculture,
)


# Reduced bootstrap iteration count for interactive scoring. The batch
# pipeline uses DEFAULT_N_BOOTSTRAP = 1000 for analysis; the interactive
# service uses fewer to hit the sub-minute latency target. Point estimates
# and tract allocation are unchanged; coefficient CIs widen proportionally,
# which the LLM does not surface anyway (see cohort_api_spec.md §3.3).
INTERACTIVE_N_BOOTSTRAP = 200

# Tract population variable used as the size term in every cohort's
# regression. Pre-fetched at startup and seeded into the marginal cache
# so it never re-fetches.
TRACT_POP_VAR = "B01003_001E"


# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------


@dataclass
class ServerState:
    """Long-lived state for the scoring service. Loaded once at startup.

    Holds everything the per-cohort pipeline needs that does not change
    between requests: the PUMS microdata DataFrame, the tract<->PUMA
    crosswalk and its derived structures, the tract population baseline,
    PUMA spatial structures, and a marginal cache shared across cohorts.

    The marginal cache is the highest-leverage cache: most cohorts share
    several ACS table codes with other cohorts (B19001_* income series,
    B25024_* housing structure, etc.), so a hit there saves a ~5-15s
    Census-API round-trip per shared variable.
    """

    pums_df: pd.DataFrame
    tract_to_puma: dict[str, str]
    tracts_by_puma: dict[str, list[str]]
    puma_pop: dict[str, float]
    tract_pop: dict[str, float]
    spatial_weights: dict[str, list[str]] | None
    puma_centroids: dict[str, tuple[float, float]] | None
    marginal_cache: dict[str, TractMarginal] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "ServerState":
        """One-time initialization. Slow on first run (downloads PUMS and
        ACS tables); fast on subsequent runs (everything is parquet-cached
        by the underlying pipeline functions).
        """
        print("[service] loading server state...")
        t0 = time.time()

        # PUMA shapefiles are needed by build_puma_queen_neighbors and
        # build_puma_centroids below. The shapefiles live in cache/puma_shp/
        # and are extracted as a side effect of fetch_pumas_geojson(). If
        # they are already on disk, skip the fetch entirely; the request
        # to the TIGER server can hang for long minutes on a slow socket
        # (the underlying requests.get only enforces a per-read timeout,
        # not a total timeout, so a server that dribbles bytes never trips
        # the 120s ceiling).
        shp_dir = CACHE / "puma_shp"
        if shp_dir.exists() and any(shp_dir.glob("*.shp")):
            print(f"[service] PUMA shapefiles cached at {shp_dir}; skipping TIGER fetch")
        else:
            fetch_pumas_geojson()

        df = fetch_pums()
        print(
            f"[service] PUMS loaded: {len(df):,} records, "
            f"{df['PUMA'].nunique()} PUMAs ({time.time() - t0:.1f}s)"
        )

        crosswalk = fetch_tract_puma_crosswalk()
        tract_to_puma = dict(zip(crosswalk["tract_geoid"], crosswalk["puma"]))

        tracts_by_puma: dict[str, list[str]] = defaultdict(list)
        for t, p in tract_to_puma.items():
            tracts_by_puma[p].append(t)

        # Tract population baseline. Seeded into the marginal cache because
        # every cohort's regression uses it as the size term and we never
        # want to re-fetch it.
        tract_pop_marg = fetch_acs_tract_marginal(TRACT_POP_VAR)
        tract_pop = tract_pop_marg.estimates

        puma_pop: dict[str, float] = defaultdict(float)
        for t, p in tract_to_puma.items():
            puma_pop[p] += tract_pop.get(t, 0.0)

        try:
            spatial_weights = build_puma_queen_neighbors(CACHE / "puma_shp")
            print(f"[service] spatial weights: {len(spatial_weights)} PUMAs")
        except Exception as e:
            print(f"[service] warning: spatial weights unavailable ({e})")
            spatial_weights = None

        try:
            puma_centroids = build_puma_centroids(CACHE / "puma_shp")
            print(f"[service] centroids: {len(puma_centroids)} PUMAs")
        except Exception as e:
            print(f"[service] warning: centroids unavailable ({e})")
            puma_centroids = None

        marginal_cache: dict[str, TractMarginal] = {TRACT_POP_VAR: tract_pop_marg}

        print(f"[service] ready ({time.time() - t0:.1f}s total)")
        return cls(
            pums_df=df,
            tract_to_puma=tract_to_puma,
            tracts_by_puma=dict(tracts_by_puma),
            puma_pop=dict(puma_pop),
            tract_pop=tract_pop,
            spatial_weights=spatial_weights,
            puma_centroids=puma_centroids,
            marginal_cache=marginal_cache,
        )


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


# Operators whose `value` is a list and whose semantics are
# order-insensitive (membership in a set). We sort the value list before
# hashing so two definitions that differ only in list order hash the same.
# `range` is excluded deliberately: its value is a positional [min, max]
# pair where order is meaningful.
_SET_VALUED_OPS = {"in", "occupation_soc_major", "industry_naics"}


def _normalize_value(op: str, value: Any) -> Any:
    """Normalize a vector entry's `value` for hashing.

    Order-insensitive ops get their value list sorted and deduplicated;
    everything else passes through unchanged.
    """
    if op in _SET_VALUED_OPS and isinstance(value, list):
        # Sort by the JSON-serialized form so heterogeneous types
        # (ints alongside strings, for example) get a stable order.
        return sorted(set(value), key=lambda x: json.dumps(x, sort_keys=True))
    return value


def canonical_cohort_hash(cohort_def: dict) -> str:
    """Content-hash the computational inputs of a cohort definition.

    Hashes threshold + sorted tract_marginals + normalized vector. Excludes
    name, vibe, and proxy_gap (presentation only). Returns the first 12
    hex chars of SHA-256.

    Normalization handles cosmetic differences that should NOT produce
    different hashes:
      - tract_marginals: sorted, deduplicated
      - vector entries: sorted by (field, op, value)
      - vector entry `value` for set-valued ops (in, occupation_soc_major,
        industry_naics): sorted, deduplicated
      - `required: false` treated as absent
      - `weight` rounded to two decimals

    See cohort_api_spec.md §2.5.
    """
    threshold = round(
        float(cohort_def.get("threshold", DEFAULT_MEMBERSHIP_THRESHOLD)), 4
    )
    marginals = sorted(set(parse_marginal_specs(cohort_def)))

    vector: list[dict[str, Any]] = []
    for entry in cohort_def.get("vector", []):
        norm: dict[str, Any] = {
            "field": entry["field"],
            "op": entry["op"],
            "value": _normalize_value(entry["op"], entry["value"]),
            "weight": round(float(entry.get("weight", 1.0)), 2),
        }
        # required:false is equivalent to absent; normalize accordingly so
        # cosmetic differences in request shape do not change the hash.
        if entry.get("required"):
            norm["required"] = True
        vector.append(norm)
    vector.sort(
        key=lambda e: (
            e["field"],
            e["op"],
            json.dumps(e["value"], sort_keys=True),
        )
    )

    canonical = json.dumps(
        {"threshold": threshold, "tract_marginals": marginals, "vector": vector},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Derived stats
# ---------------------------------------------------------------------------


def compute_gini(values: list[float]) -> float:
    """Gini coefficient of a list of non-negative values.

    Uses the standard sorted-values formulation:
        G = (2 * Σ_i (i * x_i)) / (n * Σ_i x_i) - (n + 1) / n

    Returns 0 for an empty list, all-zeros, or all-equal lists. Bounded
    to [0, 1] defensively against floating-point edge cases.
    """
    if not values:
        return 0.0
    vals = sorted(v for v in values if v is not None and v >= 0)
    n = len(vals)
    s = sum(vals)
    if s <= 0 or n == 0:
        return 0.0
    weighted_sum = sum((i + 1) * v for i, v in enumerate(vals))
    g = (2 * weighted_sum) / (n * s) - (n + 1) / n
    return max(0.0, min(1.0, g))


def _format_marginal_reliability(reliability_list: list[dict]) -> str:
    """Human-readable summary of per-marginal CV diagnostics. Used by the
    LLM in conversational prose. Empty string if no reliability data
    (cohort had no tract marginals)."""
    if not reliability_list:
        return ""
    parts = []
    for r in reliability_list:
        var = r.get("variable", "?")
        n_eval = r.get("n_tracts_evaluated", 0)
        n_caution = r.get("n_caution", 0)
        n_unrel = r.get("n_unreliable", 0)
        if n_eval == 0:
            parts.append(f"{var}: no tracts evaluated")
            continue
        pct_caution = round(100 * n_caution / n_eval)
        pct_unrel = round(100 * n_unrel / n_eval)
        parts.append(f"{var}: {pct_caution}% caution, {pct_unrel}% unreliable")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Single-cohort scoring
# ---------------------------------------------------------------------------


def score_one_cohort(state: ServerState, cohort_def: dict) -> dict:
    """Run the full pipeline for one cohort and return a response dict.

    Response shape (matches ``docs/cohort_api_spec.md`` §3.1):

        {
          "id":           "<12-hex content hash>",
          "name":         "<cohort display name>",
          "tract_scores": {"<tract_geoid>": {"<id>": <score>}, ...},
          "stats":        {<raw statistical quantities — see spec §3.3>}
        }

    The hash-as-id ensures structurally identical cohort definitions
    collapse to a single cache entry regardless of cosmetic differences
    (name, vibe, vector entry order). Display name is reflected back as
    a convenience for callers that want to surface it without retaining
    the original request.
    """
    # The id is the content hash. We override whatever id the caller
    # may have set, so two definitions with cosmetically different ids
    # but identical computational inputs end up with the same hash and
    # the same cache file downstream.
    sub_id = canonical_cohort_hash(cohort_def)
    cohort_def_with_id = {**cohort_def, "id": sub_id}
    threshold = float(
        cohort_def_with_id.get("threshold", DEFAULT_MEMBERSHIP_THRESHOLD)
    )

    # 1. Score PUMS records: gate, fit score, member indicator.
    gate, fit_score = score_subculture(state.pums_df, cohort_def_with_id)
    member = compute_membership(gate, fit_score, threshold)

    pwgtp = state.pums_df["PWGTP"]
    weighted_gate_pass = float((gate.astype(float) * pwgtp).sum())
    weighted_member_count = float((member * pwgtp).sum())
    weighted_soft_total = float((fit_score * pwgtp).sum())
    if weighted_member_count > 0:
        mean_fit_per_member = float(
            ((fit_score * member) * pwgtp).sum() / weighted_member_count
        )
    else:
        mean_fit_per_member = 0.0

    # 2. PUMA-level aggregation.
    puma_scores_all = aggregate_to_puma(state.pums_df, {sub_id: member})
    cohort_puma_scores = {
        p: vals.get(sub_id, 0.0) for p, vals in puma_scores_all.items()
    }

    # 3. PUMS sampling variance per PUMA via SDR (used as σ²_e in FH).
    puma_var_all = aggregate_to_puma_variance(state.pums_df, {sub_id: member})
    if puma_var_all:
        cohort_puma_variance: dict[str, float] | None = {
            p: vals.get(sub_id, 0.0) for p, vals in puma_var_all.items()
        }
    else:
        cohort_puma_variance = None

    # 4. Fetch this cohort's tract marginals, hitting the shared cache for
    #    any variable another cohort has already pulled this session.
    marginal_specs = parse_marginal_specs(cohort_def_with_id)
    marginal_estimates: list[dict[str, float]] = []
    marginal_moes: list[dict[str, float]] = []
    marginal_names: list[str] = []
    for var in marginal_specs:
        cached = state.marginal_cache.get(var)
        if cached is None:
            cached = fetch_acs_tract_marginal(var)
            state.marginal_cache[var] = cached
        marginal_estimates.append(cached.estimates)
        marginal_moes.append(cached.moes)
        marginal_names.append(var)

    # 5. Tract distribution: ridge+NNLS, FH+EBLUP, bootstrap, raking.
    #    This is the heavy compute and the bottleneck for latency. We use
    #    the lower interactive bootstrap iteration count; the analytical
    #    1000-iter run only happens in the batch pipeline.
    _, tract_scores_for_cohort, summary = _process_one_cohort_for_tracts(
        sub_id,
        marginal_estimates,
        marginal_names,
        state.tracts_by_puma,
        state.tract_to_puma,
        state.puma_pop,
        state.tract_pop,
        cohort_puma_scores,
        cohort_puma_variance,
        state.spatial_weights,
        state.puma_centroids,
        INTERACTIVE_N_BOOTSTRAP,
        1,  # bootstrap_n_jobs (serial; the service is itself the unit of parallelism)
        marginal_moes,
    )

    # 6. Derived stats from the model summary.
    eblup_by_puma = summary.get("eblup_by_puma", {}) or {}
    concentration_index = compute_gini(list(eblup_by_puma.values()))
    n_pumas_nonzero = sum(1 for v in eblup_by_puma.values() if v and v > 0)

    # 7. Compose stats payload. Every field is a raw, well-defined
    #    statistical quantity (see spec §3.3 for citations).
    fh = summary.get("fay_herriot") or {}
    stats = {
        "weighted_member_count": int(round(weighted_member_count)),
        "weighted_gate_pass": int(round(weighted_gate_pass)),
        "weighted_soft_total": int(round(weighted_soft_total)),
        "mean_fit_per_member": round(mean_fit_per_member, 4),
        "concentration_index": round(concentration_index, 4),
        "n_pumas_nonzero": n_pumas_nonzero,
        "n_pumas_total": int(summary.get("n_pumas", 281)),
        "r_squared": _round_or_none(summary.get("r_squared"), 4),
        "loocv_r_squared": _round_or_none(summary.get("loocv_r_squared"), 4),
        "morans_i_residual": _round_or_none(summary.get("morans_i_residual"), 4),
        "morans_i_z_score": _round_or_none(summary.get("morans_i_z_score"), 3),
        "morans_i_p_value": _round_or_none(summary.get("morans_i_p_value"), 6),
        "residual_std": _round_or_none(summary.get("residual_std"), 2),
        "lambda_chosen": summary.get("lambda"),
        "fay_herriot_median_gamma": _round_or_none(fh.get("median_gamma"), 4),
        "feature_names": summary.get("feature_names", []),
        "feature_coefs": [
            _round_or_none(c, 4) for c in summary.get("coefs", [])
        ],
        "marginal_reliability_summary": _format_marginal_reliability(
            summary.get("marginal_reliability", [])
        ),
    }

    # Compose the tract scores object in the same nested shape the existing
    # batch pipeline emits ({tract: {cohort_id: score}}), so the frontend
    # merge logic that handles multi-cohort scores does not need a special
    # case for user-generated cohorts. Tracts with zero or missing scores
    # are omitted to keep the file small.
    tract_scores = {
        t: {sub_id: round(v, 1)}
        for t, v in tract_scores_for_cohort.items()
        if v is not None and v > 0
    }

    return {
        "id": sub_id,
        "name": cohort_def.get("name", sub_id),
        "tract_scores": tract_scores,
        "stats": stats,
    }


def _round_or_none(value: Any, digits: int) -> float | None:
    """Round a float to ``digits`` places, propagating None for missing
    diagnostics (e.g., when spatial weights were unavailable so Moran's I
    couldn't be computed)."""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
