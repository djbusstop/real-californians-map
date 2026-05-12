"""Small-area estimation primitives for tract-level cohort allocation.

Owns the statistical machinery that distributes PUMA-level cohort counts
to census tracts: ACS marginal fetching, ridge+NNLS regression with
LOOCV-selected lambda, Fay-Herriot EBLUP shrinkage (Prasad-Rao MoM),
Conley spatial HAC standard errors, non-parametric percentile bootstrap
CIs, Moran's I on residuals, and MOE-weighted within-PUMA raking. The
per-cohort orchestrator `_process_one_cohort_for_tracts` is the single
entry point service.py calls per /score request.

Methodology references live in METHODOLOGY.md and in the docstrings of
each function. Numerical primitives are unchanged from when this code
lived in pipeline.py; this module is purely a reorganization.
"""

from __future__ import annotations

import json
import warnings
from typing import NamedTuple

import joblib
import numpy as np
import pandas as pd
import requests
from scipy.optimize import nnls

# Cache directory and Census API base live in data_prep (formerly
# pipeline.py); imported here so we don't duplicate the constants.
from data_prep import CACHE


# ----------------------------------------------------------------------------
# Methodology constants. See METHODOLOGY.md for the rationale of each.
# ----------------------------------------------------------------------------

# Ridge lambda candidates for LOOCV. Log-spaced from near-OLS to heavy
# shrinkage.
LAMBDA_GRID: list[float] = [0.0, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]

# LOOCV R-squared threshold to accept the regression. Below this, the
# cohort falls back to equal-weight share-blend. Negative LOOCV R-squared
# means the model generalises worse than the unconditional mean.
LOOCV_R2_THRESHOLD: float = 0.05

# Conley spatial HAC bandwidth in kilometres. Fixed (not adaptive); see
# METHODOLOGY.md "Diagnostics" for the rationale.
CONLEY_BANDWIDTH_KM: float = 75.0

# Bootstrap iteration count for percentile-CI estimation per cohort.
DEFAULT_N_BOOTSTRAP: int = 1000

# Minimum number of successful bootstrap fits required before we report
# a CI. Below this we report NaN rather than risk a noisy percentile
# interval.
BOOTSTRAP_MIN_FITS: int = 100

# VIF "infinity" threshold. R-squared values above this are reported as
# VIF = inf rather than 1/(1-R-squared); avoids float-noise artifacts
# on truly collinear pairs.
VIF_INFINITY_THRESHOLD_R2: float = 1 - 1e-9

# ACS marginal reliability thresholds (coefficient of variation, CV).
# CV = (MOE / 1.645) / estimate. The denominator 1.645 is the z-score
# for the 90% confidence level (ACS publishes MOEs at 90% by
# convention). Thresholds from Census Bureau (2020), Understanding and
# Using American Community Survey Data, chapter 7.
#   CV < 12%               : reliable
#   12% <= CV < 40%        : use with caution
#   CV >= 40%              : not reliable
CENSUS_CV_CAUTION_THRESHOLD: float = 0.12
CENSUS_CV_UNRELIABLE_THRESHOLD: float = 0.40
ACS_MOE_Z90: float = 1.645

# ACS aggregated-tables API. The PUMS endpoint had reliability issues
# (intermittent 500s) so we use the aggregated tables endpoint for
# tract-level marginal fetching.
ACS_API: str = "https://api.census.gov/data/2023/acs/acs5"


class TractMarginal(NamedTuple):
    """Per-tract ACS marginal: point estimate and 90% margin of error.

    Both dicts are keyed by tract GEOID. Suppressed or non-applicable cells:
      - estimates: stored as 0.0 (consistent with the pre-MOE behaviour).
      - moes: stored as float('nan') so downstream reliability calculations
              can distinguish a published 0.0 MOE (controlled total) from an
              unpublished or special-coded cell.

    Per U.S. Census Bureau convention, MOEs are published at the 90% confidence
    level. The corresponding standard error is MOE / 1.645 (see ACS_MOE_Z90).

    NamedTuple (rather than a plain function returning a 2-tuple) gives
    callers ``.estimates`` and ``.moes`` as named, type-annotated
    attributes without taking on dataclass overhead. The struct is
    immutable and trivially picklable, which the joblib bootstrap path
    expects when marginal data crosses worker boundaries.
    """

    estimates: dict[str, float]
    moes: dict[str, float]


def _compute_tract_cv(estimate: float, moe: float) -> float | None:
    """Coefficient of variation for one ACS tract cell.

    CV = (MOE / 1.645) / estimate, where 1.645 is the z-score for the 90%
    confidence level at which ACS publishes MOEs. Returns None when CV is
    undefined: estimate ≤ 0, MOE is NaN, or MOE is negative (suppression
    code passed through).

    References:
      - U.S. Census Bureau (2020), Understanding and Using American
        Community Survey Data: What All Data Users Need to Know, chapter 7
        (definition and reliability bands).
      - Spielman & Singleton (2015), "Studying Neighborhoods Using
        Uncertain Data from the American Community Survey: A Contextual
        Approach," Annals AAG 105(5) (small-area implications).
    """
    if estimate is None or moe is None:
        return None
    if estimate <= 0:
        return None
    if not np.isfinite(moe) or moe < 0:
        return None
    return (moe / ACS_MOE_Z90) / estimate


def _summarize_marginal_reliability(
    estimates: dict[str, float],
    moes: dict[str, float],
    var_name: str | None = None,
) -> dict:
    """Per-marginal reliability summary keyed by ACS CV bands.

    Returns counts and CV percentiles for one tract-level marginal, used
    downstream by the model-summary stage so a reviewer can see which
    cohort's marginals carried noisy ACS sampling estimates. Bands follow
    the Census Bureau's published thresholds: CV < 12% reliable, 12% <= CV
    < 40% caution, CV >= 40% unreliable (Census 2020 ACS Handbook, ch. 7).
    See Spielman & Singleton (2015) on why this matters for small-area
    work.

    Returns:
      variable, n_tracts_evaluated, n_suppressed_or_zero,
      n_caution, n_unreliable, median_cv, p90_cv, max_cv.
    """
    cvs: list[float] = []
    n_caution = 0
    n_unreliable = 0
    n_suppressed = 0
    for tract_geoid, est in estimates.items():
        moe = moes.get(tract_geoid, float("nan"))
        cv = _compute_tract_cv(est, moe)
        if cv is None:
            n_suppressed += 1
            continue
        cvs.append(cv)
        if cv >= CENSUS_CV_UNRELIABLE_THRESHOLD:
            n_unreliable += 1
        elif cv >= CENSUS_CV_CAUTION_THRESHOLD:
            n_caution += 1

    summary: dict[str, Any] = {
        "variable": var_name,
        "n_tracts_evaluated": len(cvs),
        "n_suppressed_or_zero": n_suppressed,
        "n_caution": n_caution,
        "n_unreliable": n_unreliable,
        "median_cv": float(np.median(cvs)) if cvs else None,
        "p90_cv": float(np.percentile(cvs, 90)) if cvs else None,
        "max_cv": float(np.max(cvs)) if cvs else None,
    }
    return summary


def fetch_acs_tract_marginal(var: str) -> TractMarginal:
    """Download, parse, and cache one ACS variable for every California tract.

    "Fetch" understates what this does: it hits the Census aggregated-
    tables API for the variable's point estimate and the companion
    MOE variable (var ending in 'M'), parses both responses into
    GEOID-keyed dicts, persists them to local JSON caches under
    ``cache/acs/``, and returns a TractMarginal pair. Subsequent calls
    for the same variable read from the JSON cache rather than hitting
    the network, so per-cohort scoring is fast once the shared cache
    is warm.

    Why the aggregated-tables endpoint rather than the PUMS endpoint:
    the PUMS API has had intermittent reliability issues (500s on
    small queries); the aggregated tables are the published 5-Year
    tract estimates we want anyway, and the API serves them
    reliably.

    Why MOEs are stored separately: downstream small-area allocation
    weights tracts by inverse marginal variance (see Cochran 1937),
    so we need both the point estimate and the published MOE per
    tract. The full reliability disclosure follows Census Bureau
    (2020) ACS Handbook, ch. 7.

    The cache is skipped if the API returns an entirely-zero response — some
    detailed tables (e.g., B16001 detailed-language, B11009 same-sex partner
    households) appear to be tract-level-suppressed in 2023 ACS 5-Year and
    return all zeros from the public Detailed Tables API. Caching such a
    response would silently break downstream cohorts whose marginals depend
    on it, so we warn and refuse to cache. The next pipeline run will retry.
    """
    # MOE variable code follows the ACS convention: the same code with the
    # 'E' (estimate) suffix replaced by 'M' (margin of error). E.g.
    # B11001_006E -> B11001_006M. We refuse non-_E inputs so callers don't
    # accidentally pass percent estimates (_PE) or annotations (_EA).
    if not var.endswith("E"):
        raise ValueError(
            f"Expected ACS variable code to end with 'E', got {var!r}. "
            "Only estimate variables are supported (e.g., B11001_006E)."
        )
    moe_var = var[:-1] + "M"

    cached_e = CACHE / f"acs_tract_{var}.json"
    cached_m = CACHE / f"acs_tract_{moe_var}.json"
    if cached_e.exists() and cached_m.exists():
        estimates = json.loads(cached_e.read_text())
        moes = json.loads(cached_m.read_text())
        # NaN doesn't round-trip through JSON; values written as `null` come
        # back as Python None and need to be restored.
        moes = {
            k: (float(v) if v is not None else float("nan")) for k, v in moes.items()
        }
        # Defensive: even if a previous run wrote a bad cache (e.g., from
        # before this guard was added), surface the issue at load time.
        if estimates and not any(v != 0 for v in estimates.values()):
            print(
                f"[warn] cached tract marginal {var} is 100% zeros; "
                "possible tract-level suppression. Delete "
                f"cache/acs_tract_{var}.json and re-run to retry."
            )
        return TractMarginal(estimates=estimates, moes=moes)

    # Fetch estimate and MOE together in a single API call. This is the
    # cold-start bottleneck for cohorts whose marginals aren't already in
    # the shared marginal_cache: each new ACS variable is a ~5-15s
    # network round-trip to the Census Detailed Tables API.
    url = f"{ACS_API}?get=NAME,{var},{moe_var}&for=tract:*&in=state:06"
    print(f"[fetch] ACS tract var {var} (with MOE {moe_var})")
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    # The Census API occasionally returns 200 with a non-JSON body (HTML
    # error page, plain-text "error: variable does not exist", empty
    # response). Treat that as the same class of "this marginal cannot
    # be fetched" failure as the all-zeros suppression case below:
    # return an empty TractMarginal, do not cache, and let the
    # downstream model fall through to its share-blend fallback.
    try:
        rows = r.json()
    except ValueError as e:
        body_preview = r.text[:200].replace("\n", " ")
        print(
            f"[warn] {var}: API returned 200 but non-JSON body "
            f"({type(e).__name__}: {e}). Body preview: {body_preview!r}. "
            "This usually means the variable code is not published at the "
            "tract level for this ACS vintage. Not caching."
        )
        return TractMarginal(estimates={}, moes={})

    if not rows or not isinstance(rows, list):
        print(
            f"[warn] {var}: API returned unexpected JSON shape ({type(rows).__name__}). "
            "Not caching."
        )
        return TractMarginal(estimates={}, moes={})

    header, *data = rows
    state_idx = header.index("state")
    county_idx = header.index("county")
    tract_idx = header.index("tract")
    e_idx = header.index(var)
    m_idx = header.index(moe_var)

    estimates: dict[str, float] = {}
    moes: dict[str, float] = {}
    for row in data:
        geoid = row[state_idx] + row[county_idx] + row[tract_idx]

        # Parse estimate. ACS uses negative special codes for various
        # suppression / not-applicable reasons (e.g., -555555555). Clamp those
        # to 0 to preserve the pre-MOE behavior of downstream code.
        try:
            raw_est = (
                float(row[e_idx]) if row[e_idx] not in (None, "") else 0.0
            )
        except (TypeError, ValueError):
            raw_est = 0.0
        estimates[geoid] = max(raw_est, 0.0)

        # Parse MOE. ACS publishes MOEs as non-negative reals; negative codes
        # indicate the MOE is not published for that cell. Treat all such
        # cases as NaN so the reliability calculation can distinguish them
        # from a genuinely published 0.0 MOE (controlled total).
        try:
            raw_moe = (
                float(row[m_idx]) if row[m_idx] not in (None, "") else float("nan")
            )
        except (TypeError, ValueError):
            raw_moe = float("nan")
        moes[geoid] = raw_moe if (np.isfinite(raw_moe) and raw_moe >= 0) else float("nan")

    nonzero = sum(1 for v in estimates.values() if v != 0)
    total = sum(estimates.values())
    if estimates and nonzero == 0:
        # All-zero response. Warn and refuse to cache so the next run retries
        # rather than silently using the bad data forever.
        print(
            f"[warn] {var}: API returned {len(estimates):,} tracts, ALL ZEROS. "
            "This usually indicates tract-level suppression for this table; "
            "consider switching to a collapsed/published alternative (e.g., "
            "C16001 instead of B16001). Not caching."
        )
        return TractMarginal(estimates=estimates, moes=moes)

    # NaN is not valid JSON; serialise as `null` and the reload path restores
    # them to float('nan').
    cached_e.write_text(json.dumps(estimates))
    cached_m.write_text(
        json.dumps({k: (v if np.isfinite(v) else None) for k, v in moes.items()})
    )

    # Per-marginal reliability is already summarised inside
    # `_process_one_cohort_for_tracts` and persisted in the cohort's
    # model summary; we don't duplicate it as a fetch-time print.
    print(
        f"[fetch] {var}: {len(estimates):,} tract values "
        f"({nonzero:,} nonzero, sum={total:,.0f})"
    )
    return TractMarginal(estimates=estimates, moes=moes)


def _phase1_share_blend(
    puma_score: float,
    tract_geoids: list[str],
    marginals_per_tract: dict[str, list[float]],
    weights: list[float],
) -> dict[str, float]:
    """Phase 1 fallback: weighted convex combination of normalized marginal shares
    within a PUMA. Each marginal proposes a tract distribution; we average them
    using the cohort-specified weights. Robust to zeros and missing values.
    Closed-form equivalent of IPF on a single-axis distribution problem."""
    if puma_score <= 0 or not tract_geoids:
        return {}
    weight_total = sum(weights)
    if weight_total <= 0:
        return {t: puma_score / len(tract_geoids) for t in tract_geoids}

    n_marg = len(weights)
    sums = [0.0] * n_marg
    for t in tract_geoids:
        vals = marginals_per_tract.get(t, [0.0] * n_marg)
        for i in range(n_marg):
            sums[i] += vals[i]

    out: dict[str, float] = {}
    if all(s <= 0 for s in sums):
        # Every marginal is zero across this PUMA; uniform fallback.
        share = 1.0 / len(tract_geoids)
        return {t: round(puma_score * share, 2) for t in tract_geoids}

    for t in tract_geoids:
        vals = marginals_per_tract.get(t, [0.0] * n_marg)
        share = 0.0
        used_weight = 0.0
        for i in range(n_marg):
            if sums[i] > 0:
                share += weights[i] * (vals[i] / sums[i])
                used_weight += weights[i]
        if used_weight > 0:
            share /= used_weight
        out[t] = round(puma_score * share, 2)
    return out


def _fit_ridge_nnls(X_train, y_train, lam: float):
    """Ridge regression with non-negativity constraint on coefficients.

    Solves min ||y - Xβ||² + λ||β||² s.t. β ≥ 0 by augmenting the design matrix:
      X_aug = [X; √λ · I],   y_aug = [y; 0]
    and running NNLS (Lawson & Hanson 1974) on the augmented system.
    """
    n_f = X_train.shape[1]
    sqrt_lam = np.sqrt(max(lam, 0.0))
    X_aug = np.vstack([X_train, sqrt_lam * np.eye(n_f)])
    y_aug = np.concatenate([y_train, np.zeros(n_f)])
    # scipy's nnls computes a final residual norm via matmul that can trip
    # numpy overflow/invalid warnings on near-singular leave-one-out splits;
    # the returned coefficients are still correct, so silence the noise.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            try:
                coefs, _ = nnls(X_aug, y_aug, maxiter=5000)
            except Exception:
                return None
    return coefs


def _estimate_sigma2_u_prasad_rao(
    y, X, beta, sigma2_e
):
    """Prasad-Rao method-of-moments estimator for the random-effect variance
    σ²_u in the Fay-Herriot area-level model.

    σ̂²_u = max(0, (1/(m − p)) · [Σ_p (y_p − X_p β̂)² − Σ_p σ²_e_p])

    where m is the number of areas and p is the number of parameters.
    Reference: Prasad & Rao 1990, *JASA* 85(409), 163-171.
    """
    m = len(y)
    p = X.shape[1]
    if m <= p:
        return 0.0
    residuals_sq = (y - X @ beta) ** 2
    estimate = (residuals_sq.sum() - sigma2_e.sum()) / max(m - p, 1)
    return float(max(0.0, estimate))


def _compute_eblup(y, X, beta, sigma2_e, sigma2_u):
    """Empirical Best Linear Unbiased Predictor for each area under the
    Fay-Herriot model:

        ŷ_FH_p = X_p β̂ + γ_p · (y_p − X_p β̂),    γ_p = σ²_u / (σ²_u + σ²_e_p)

    γ_p is the shrinkage factor: when sampling variance σ²_e_p is large
    relative to between-area variance σ²_u, γ_p is small and the area is
    shrunk toward the synthetic regression prediction. When σ²_e_p is small,
    γ_p is near 1 and the direct estimate is preserved.

    Returns (eblup_predictions, gamma_per_area).
    """
    synthetic = X @ beta
    direct_residual = y - synthetic
    denom = sigma2_u + sigma2_e
    gamma = np.where(denom > 0, sigma2_u / denom, 0.0)
    eblup = synthetic + gamma * direct_residual
    return eblup, gamma


def _compute_conley_se(X_z, residuals, lam, puma_ids, centroids, bandwidth_km=CONLEY_BANDWIDTH_KM):
    """Conley spatial HAC standard errors (Conley 1999, *J. Econometrics* 92).

    Computes V = (X'X + λI)⁻¹ · X' Ω X · (X'X + λI)⁻¹ where Ω is the
    distance-weighted residual cross-product matrix using a Bartlett kernel:

        Ω_ij = max(0, 1 − d_ij / h) · ε_i · ε_j

    Returns standard errors (sqrt of diagonal) for each coefficient.

    The (X'X + λI)⁻¹ form is the ridge-adjusted analog of the OLS sandwich
    estimator. With the NNLS non-negativity constraint, this is approximate
    for any coefficient that hit the boundary β = 0 (whose effective SE is
    degenerate); the bootstrap procedure is the rigorous companion estimate.
    """
    n, p = X_z.shape
    if len(puma_ids) != n or not centroids:
        return [float("nan")] * p

    coords = np.array(
        [centroids.get(pid, (np.nan, np.nan)) for pid in puma_ids],
        dtype=float,
    )
    if np.isnan(coords).any():
        # Some PUMAs lack centroids; fall back to non-spatial OLS-like SE.
        return [float("nan")] * p

    # Approximate great-circle distance in km via haversine-like formula on
    # lat/lon. For the CA bounding box this is well within tolerance.
    lat = np.deg2rad(coords[:, 1])
    lon = np.deg2rad(coords[:, 0])
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    d_km = 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

    K = np.maximum(0.0, 1.0 - d_km / bandwidth_km)
    Omega = K * np.outer(residuals, residuals)

    # The sandwich matmul chain can produce extreme intermediate values for
    # tightly-gated cohorts where many residuals are zero or near-zero. Outputs
    # are clipped to non-negative (variance can't be negative) and any non-finite
    # diagonal element is replaced with 0 before the sqrt, so the SE for that
    # coefficient is reported as 0.0 rather than NaN. The bootstrap CI is the
    # rigorous companion estimate when this happens.
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        XtX_lam_inv = np.linalg.pinv(X_z.T @ X_z + lam * np.eye(p))
        V = XtX_lam_inv @ X_z.T @ Omega @ X_z @ XtX_lam_inv
        diag_V = np.diag(V)
        diag_V = np.where(np.isfinite(diag_V), diag_V, 0.0)
        se = np.sqrt(np.maximum(diag_V, 0.0))
    return [float(s) for s in se]


def _one_bootstrap_resample(seed_b, Xz, y_centered, lam):
    """One bootstrap resample-and-fit. Top-level so it picklable for joblib.

    Each resample uses its own seeded RNG so that results are reproducible
    under either serial or parallel execution.
    """
    rng_b = np.random.default_rng(seed_b)
    n, p = Xz.shape
    idx = rng_b.integers(0, n, size=n)
    coefs_b = _fit_ridge_nnls(Xz[idx], y_centered[idx], lam)
    if coefs_b is None:
        return np.full(p, np.nan)
    return coefs_b


def _compute_bootstrap_ci(
    Xz,
    y_centered,
    lam,
    n_bootstrap=DEFAULT_N_BOOTSTRAP,
    alpha=0.05,
    seed=42,
    n_jobs: int = 1,
):
    """Non-parametric percentile bootstrap confidence intervals for ridge+NNLS
    coefficients (Efron & Tibshirani 1993, *An Introduction to the Bootstrap*).

    Resamples PUMAs with replacement n_bootstrap times, refits the same
    ridge+NNLS model at fixed λ on each resample, and returns the (α/2, 1-α/2)
    percentile interval per coefficient.

    Parallelism: when n_jobs != 1, resamples are dispatched to a thread pool
    via joblib (threading backend, since each task is small and the underlying
    NNLS solver releases the GIL during the C-level Lawson-Hanson loop).
    Per-resample seeds are generated up front from the parent RNG so the
    coefficient sample set is identical across n_jobs settings.

    Notes:
    - λ is held fixed at the LOOCV-selected value rather than re-tuned per
      resample; this is "post-selection bootstrap" which understates total
      uncertainty by the amount due to λ-selection. Standard tradeoff for
      computational tractability (Hastie et al. 2009 §7.10.2).
    - Residuals are spatially correlated (significant Moran's I), so the
      i.i.d. resampling assumption underestimates uncertainty modestly.
      Conley SEs are reported as a spatially-aware companion estimate.

    Returns (ci_lower, ci_upper) as lists of length p.
    """
    rng = np.random.default_rng(seed)
    n, p = Xz.shape
    # Pre-generate per-resample seeds so the bootstrap sample set is identical
    # whether we run resamples serially or in parallel.
    seeds = rng.integers(0, 2**31 - 1, size=n_bootstrap)

    if n_jobs == 1:
        results = [
            _one_bootstrap_resample(int(s), Xz, y_centered, lam) for s in seeds
        ]
    else:
        results = joblib.Parallel(n_jobs=n_jobs, backend="threading")(
            joblib.delayed(_one_bootstrap_resample)(int(s), Xz, y_centered, lam)
            for s in seeds
        )
    coef_samples = np.asarray(results)

    # Drop any failed fits before computing percentiles.
    mask = ~np.isnan(coef_samples).any(axis=1)
    coef_samples = coef_samples[mask]
    if len(coef_samples) < BOOTSTRAP_MIN_FITS:
        return [float("nan")] * p, [float("nan")] * p

    lower = np.percentile(coef_samples, 100 * alpha / 2, axis=0)
    upper = np.percentile(coef_samples, 100 * (1 - alpha / 2), axis=0)
    return [float(x) for x in lower], [float(x) for x in upper]


def _compute_vifs(Xz):
    """Variance Inflation Factors for each column of standardized design matrix Xz.
    VIF_j = 1 / (1 - R²_j) where R²_j is the R² from regressing column j on the rest.
    VIF > 10 conventionally indicates problematic multicollinearity (Belsley et al. 1980).

    For columns whose R² with the others is at or above VIF_INFINITY_THRESHOLD_R2,
    we report VIF = inf rather than computing a noisy 1/(1-R²) near machine epsilon.
    """
    n_features = Xz.shape[1]
    vifs = []
    for j in range(n_features):
        X_others = np.delete(Xz, j, axis=1)
        if X_others.shape[1] == 0:
            vifs.append(1.0)
            continue
        try:
            beta_j, *_ = np.linalg.lstsq(X_others, Xz[:, j], rcond=None)
            x_pred = X_others @ beta_j
            ss_res = float(np.sum((Xz[:, j] - x_pred) ** 2))
            ss_tot = float(np.sum(Xz[:, j] ** 2))  # already mean-zero
            r2_j = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            if r2_j < VIF_INFINITY_THRESHOLD_R2:
                vifs.append(float(1.0 / (1.0 - r2_j)))
            else:
                vifs.append(float("inf"))
        except Exception:
            vifs.append(float("nan"))
    return vifs


def _fit_area_level_model(
    puma_scores: dict[str, float],
    puma_pop: dict[str, float],
    puma_marginals: list[dict[str, float]],
    marginal_names: list[str],
    spatial_weights: dict[str, list[str]] | None = None,
    puma_score_variance: dict[str, float] | None = None,
    puma_centroids: dict[str, tuple[float, float]] | None = None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    bootstrap_n_jobs: int = 1,
) -> dict | None:
    """Fit area-level synthetic SAE model (Fay-Herriot family) with NNLS+Ridge.

    Model: y(p) = mean(y) + Σ_k β_k · z_k(p) + ε(p),
    where z_k(p) is column k of the design matrix (population + each marginal)
    standardized to mean 0, std 1 across PUMAs, and β_k ≥ 0.

    - Standardization (z-score) puts all predictors on a common scale so the
      ridge L2 penalty applies uniformly (ESL §3.4).
    - Non-negative coefficients (Lawson & Hanson 1974) prevent nonsensical
      "more X predicts less Y" results when both are counts.
    - Ridge regularization (Hoerl & Kennard 1970) handles multicollinearity
      without zero-truncating correlated predictors as plain OLS via SVD does.
    - λ selected per cohort by leave-one-PUMA-out cross-validation.

    Returns model dict with coefficients, standardization params, and
    diagnostics (R², LOOCV R², residual std, VIF per predictor, condition
    number, optional Moran's I on residuals if spatial_weights given).
    """
    pumas_aligned = sorted(set(puma_scores) & set(puma_pop))
    if len(pumas_aligned) < 8:
        return None

    rows = []
    targets = []
    keep_pumas = []
    for p in pumas_aligned:
        pop_p = puma_pop[p]
        if pop_p <= 0:
            continue
        row = [pop_p] + [m.get(p, 0.0) for m in puma_marginals]
        rows.append(row)
        targets.append(puma_scores[p])
        keep_pumas.append(p)

    if len(rows) < 8:
        return None

    X = np.asarray(rows, dtype=float)
    y = np.asarray(targets, dtype=float)
    feature_names = ["population"] + list(marginal_names)

    # Standardize predictors (z-score). Skip features with zero variance.
    X_means = X.mean(axis=0)
    X_stds = X.std(axis=0, ddof=0)
    valid = X_stds > 0
    Xz = np.zeros_like(X)
    Xz[:, valid] = (X[:, valid] - X_means[valid]) / X_stds[valid]

    y_mean = float(y.mean())
    y_centered = y - y_mean

    # Cross-validate ridge λ by leave-one-PUMA-out across the log-spaced grid
    # defined as a module constant. Range covers near-OLS (λ≈0) to heavy shrinkage.
    lam_grid = LAMBDA_GRID
    n_obs = Xz.shape[0]
    cv_scores: dict[float, float] = {}
    # Track failures per λ. When a leave-one-out fit returns None, we record
    # y_mean as the held-out prediction (the null model) so the LOOCV R²
    # can still be computed, but we count the failure. Cohorts where many
    # splits fail at the chosen λ get their LOOCV R² flagged as unreliable
    # in the model summary so a reviewer is not misled by a result that
    # came partly from null-model fallbacks.
    cv_failed: dict[float, int] = {}
    best_lam = 0.0
    best_loocv = -float("inf")

    for lam in lam_grid:
        loo_preds = np.zeros(n_obs)
        n_failed = 0
        for i in range(n_obs):
            mask = np.ones(n_obs, dtype=bool)
            mask[i] = False
            coefs_i = _fit_ridge_nnls(Xz[mask], y_centered[mask], lam)
            if coefs_i is None:
                n_failed += 1
                loo_preds[i] = y_mean
            else:
                loo_preds[i] = float(Xz[i] @ coefs_i + y_mean)
        ss_res_loo = float(np.sum((y - loo_preds) ** 2))
        ss_tot = float(np.sum((y - y_mean) ** 2))
        loocv_r2 = 1 - ss_res_loo / ss_tot if ss_tot > 0 else 0.0
        cv_scores[lam] = loocv_r2
        cv_failed[lam] = n_failed
        if loocv_r2 > best_loocv:
            best_loocv = loocv_r2
            best_lam = lam

    # Final fit on all PUMAs at best λ.
    coefs = _fit_ridge_nnls(Xz, y_centered, best_lam)
    if coefs is None:
        return None

    preds = Xz @ coefs + y_mean
    residuals = y - preds
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum(y_centered ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Diagnostics.
    vifs = _compute_vifs(Xz)
    try:
        # Compute on the valid (non-zero-variance) columns only; zero columns
        # would make cond infinite by construction.
        Xz_valid = Xz[:, valid] if valid.any() else Xz
        cond_number = float(np.linalg.cond(Xz_valid))
    except Exception:
        cond_number = float("nan")

    moran_i: float | None = None
    moran_z: float | None = None
    moran_p: float | None = None
    if spatial_weights is not None:
        moran_i, moran_z, moran_p = _compute_morans_i(
            residuals.tolist(), keep_pumas, spatial_weights
        )

    # ── Fay-Herriot EBLUP shrinkage ──
    # If we have per-PUMA sampling variances, estimate σ²_u via Prasad-Rao
    # method-of-moments and compute the EBLUP for each area.
    fh_summary: dict | None = None
    eblup_by_puma: dict[str, float] = {}
    if puma_score_variance is not None:
        sigma2_e_array = np.array(
            [float(puma_score_variance.get(p, 0.0)) for p in keep_pumas],
            dtype=float,
        )
        if (sigma2_e_array > 0).any():
            # Suppress numpy overflow/invalid warnings in the synthetic-prediction
            # matmul. For some cohort/configs the standardized X · β can produce
            # extreme intermediate values; outputs are clipped to non-negative
            # below so the warnings are cosmetic.
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                sigma2_u = _estimate_sigma2_u_prasad_rao(
                    y, Xz, coefs, sigma2_e_array
                )
                eblup_predictions, gamma = _compute_eblup(
                    y, Xz, coefs, sigma2_e_array, sigma2_u
                )
                # Intercept the centered fit by adding y_mean back into synthetic
                # (since coefs are centered-y based; X β̂ here is z-scaled).
                synthetic_full = Xz @ coefs + y_mean
                eblup_predictions = synthetic_full + gamma * (y - synthetic_full)
            for pid, val in zip(keep_pumas, eblup_predictions):
                # Clip to non-negative and to a sane upper bound (no PUMA cohort
                # estimate should exceed PUMA population); NaN/inf collapse to 0.
                if not np.isfinite(val):
                    val = 0.0
                eblup_by_puma[pid] = float(max(0.0, val))
            fh_summary = {
                "sigma2_u": float(sigma2_u),
                "mean_sigma2_e": float(sigma2_e_array.mean()),
                "median_gamma": float(np.median(gamma)),
                "min_gamma": float(np.min(gamma)),
                "max_gamma": float(np.max(gamma)),
            }

    # ── Conley spatial HAC standard errors ──
    conley_se: list[float] | None = None
    if puma_centroids is not None:
        conley_se = _compute_conley_se(
            Xz, residuals, best_lam, keep_pumas, puma_centroids
        )

    # ── Bootstrap percentile confidence intervals ──
    boot_ci_lower: list[float] | None = None
    boot_ci_upper: list[float] | None = None
    if n_bootstrap and n_bootstrap > 0:
        boot_ci_lower, boot_ci_upper = _compute_bootstrap_ci(
            Xz,
            y_centered,
            best_lam,
            n_bootstrap=n_bootstrap,
            n_jobs=bootstrap_n_jobs,
        )

    # Count of leave-one-out splits at the chosen λ where the constrained NNLS+Ridge
    # solver returned None and the held-out prediction fell back to the unconditional
    # mean. Exposed as an engineering diagnostic for cohorts where the solver is
    # unstable on small held-in samples; not a methodological reliability claim.
    loocv_failed_at_best = int(cv_failed.get(best_lam, 0))

    return {
        "method": "ridge_nnls",
        "n_pumas": int(n_obs),
        "lambda": float(best_lam),
        "lambda_cv_grid": {f"{k:g}": float(v) for k, v in cv_scores.items()},
        "lambda_cv_failed": {f"{k:g}": int(v) for k, v in cv_failed.items()},
        "feature_names": feature_names,
        "coefs": [float(c) for c in coefs],
        "feature_means": [float(m) for m in X_means],
        "feature_stds": [float(s) for s in X_stds],
        "y_mean": float(y_mean),
        "r_squared": float(r_squared),
        "loocv_r_squared": float(best_loocv),
        "loocv_failed_splits": loocv_failed_at_best,
        "residual_std": float(np.std(residuals, ddof=1)),
        "vif": [float(v) for v in vifs],
        "condition_number": cond_number,
        "morans_i_residual": moran_i,
        "morans_i_z_score": moran_z,
        "morans_i_p_value": moran_p,
        "fay_herriot": fh_summary,
        "eblup_by_puma": eblup_by_puma,
        "conley_se": conley_se,
        "bootstrap_ci_lower": boot_ci_lower,
        "bootstrap_ci_upper": boot_ci_upper,
        "bootstrap_n": n_bootstrap,
        "puma_ids": list(keep_pumas),
    }
    # All keys in the dict above flow through to the /score response's
    # `stats` payload (see service.score_one_cohort) and into the
    # per-cohort model_summaries used by the methodology paper. None
    # are expensive to compute relative to the regression itself, so
    # there's no performance win in pruning. Editorial decisions about
    # which to *display* (in the frontend, in the paper) belong above
    # this layer, not here.


def _compute_morans_i(
    residuals: list[float],
    ids: list[str],
    neighbors: dict[str, list[str]],
):
    """Global Moran's I on residuals with binary queen-contiguity weights.

    Returns (I, z_score, p_value). Inference uses the normal-approximation
    variance (Cliff & Ord 1981); for binary symmetric W with PUMAs at this
    sample size (n≈280), it's a reasonable approximation. Two-sided p-value.

    A statistically significant Moran's I (|z| > 1.96, p < 0.05) on residuals
    indicates the linear model is missing geographic structure — a quantitative
    geographer's first diagnostic for a spatial regression.
    """
    from math import erfc, sqrt

    n = len(residuals)
    if n < 4:
        return None, None, None
    e = np.asarray(residuals, dtype=float)
    e_dev = e - e.mean()
    denom = float(np.sum(e_dev ** 2))
    if denom <= 0:
        return None, None, None

    # Build dense binary symmetric weight matrix.
    id_to_idx = {id_: i for i, id_ in enumerate(ids)}
    W = np.zeros((n, n), dtype=float)
    for id_i, ngh in neighbors.items():
        i = id_to_idx.get(id_i)
        if i is None:
            continue
        for id_j in ngh:
            j = id_to_idx.get(id_j)
            if j is None or j == i:
                continue
            W[i, j] = 1.0
    # Symmetrize defensively (queen contiguity is symmetric, but data may not be).
    W = np.maximum(W, W.T)

    s0 = float(W.sum())
    if s0 == 0:
        return None, None, None

    numerator = float(e_dev @ W @ e_dev)
    morans_i = (n / s0) * (numerator / denom)
    exp_i = -1.0 / (n - 1)

    # Variance under the normality assumption.
    s1 = 0.5 * float(np.sum((W + W.T) ** 2))
    row_sum = W.sum(axis=1)
    col_sum = W.sum(axis=0)
    s2 = float(np.sum((row_sum + col_sum) ** 2))
    var_normal = (
        (n * n * s1 - n * s2 + 3 * s0 * s0) / ((n * n - 1) * s0 * s0)
    ) - exp_i * exp_i
    if var_normal <= 0:
        return float(morans_i), None, None

    z = (morans_i - exp_i) / sqrt(var_normal)
    # Two-sided p-value via complementary error function.
    p = float(erfc(abs(z) / sqrt(2)))
    return float(morans_i), float(z), p


# This function is long because it sequences the full per-cohort
# SAE pipeline: marginal-cell pulls, per-marginal reliability
# disclosure, design-matrix assembly, regression fit, EBLUP totals,
# raking back to tracts, and assembly of the model-summary dict. Each
# step is a few lines; the length is the SAE recipe's own length.
# Splitting into smaller helpers is possible but would push state
# (lots of intermediate dicts/arrays) through extra parameter lists
# without making the recipe clearer.
def _process_one_cohort_for_tracts(
    sub_id: str,
    marginals_list: list[dict[str, float]],
    marginal_names: list[str],
    tracts_by_puma: dict[str, list[str]],
    tract_to_puma: dict[str, str],
    puma_pop: dict[str, float],
    tract_pop: dict[str, float],
    cohort_puma_scores: dict[str, float],
    cohort_puma_variance: dict[str, float] | None,
    spatial_weights: dict[str, list[str]] | None,
    puma_centroids: dict[str, tuple[float, float]] | None,
    n_bootstrap: int,
    bootstrap_n_jobs: int,
    marginal_moes: list[dict[str, float]] | None = None,
) -> tuple[str, dict[str, float], dict]:
    """Per-cohort tract-allocation worker. Top-level so joblib (loky backend)
    can pickle it across worker processes.

    Returns (sub_id, tract_scores_for_cohort, summary) where:
      - tract_scores_for_cohort: { tract_geoid: score } for this cohort only;
        the parent caller merges these into the global output dict.
      - summary: the cohort's regression model dict (or share-blend fallback dict).
    """
    from collections import defaultdict

    # PUMA-aggregated marginals (sum across tracts in each PUMA).
    puma_marginals: list[dict[str, float]] = []
    for marg in marginals_list:
        agg: dict[str, float] = defaultdict(float)
        for tract_geoid, val in marg.items():
            puma = tract_to_puma.get(tract_geoid)
            if puma is None:
                continue
            agg[puma] += val
        puma_marginals.append(dict(agg))

    # ── Per-marginal reliability disclosure ──
    # For each declared tract marginal, compute the share of tracts whose
    # ACS-published 90% MOE places the estimate in the "use with caution"
    # or "unreliable" bands of Census Bureau (2020). This is a disclosure
    # step only: the regression still uses the point estimates as inputs.
    # Spielman & Singleton (2015) develop why this disclosure matters for
    # any defensible small-area classification using ACS data.
    marginal_reliability: list[dict] = []
    if marginal_moes is not None and len(marginal_moes) == len(marginals_list):
        for name, est_dict, moe_dict in zip(marginal_names, marginals_list, marginal_moes):
            marginal_reliability.append(
                _summarize_marginal_reliability(est_dict, moe_dict, var_name=name)
            )

    # ── Try regression ──
    model = None
    if marginals_list:
        print(f"[fit] {sub_id}: ridge+NNLS with FH+Conley+bootstrap...")
        model = _fit_area_level_model(
            cohort_puma_scores,
            puma_pop,
            puma_marginals,
            marginal_names,
            spatial_weights=spatial_weights,
            puma_score_variance=cohort_puma_variance,
            puma_centroids=puma_centroids,
            n_bootstrap=n_bootstrap,
            bootstrap_n_jobs=bootstrap_n_jobs,
        )

    # Use EBLUP-shrunk PUMA totals as the raking target if available;
    # falls through to direct PUMS estimates otherwise.
    eblup_by_puma: dict[str, float] = (
        (model or {}).get("eblup_by_puma", {}) if model else {}
    )

    def raking_target(p: str) -> float:
        if eblup_by_puma and p in eblup_by_puma:
            return float(eblup_by_puma[p])
        return float(cohort_puma_scores.get(p, 0.0))

    cohort_tract_scores: dict[str, float] = {}

    if model and model.get("loocv_r_squared", -1) >= LOOCV_R2_THRESHOLD:
        # Predict tract-level shares, then rake within each PUMA.
        # The fit is on z-standardized PUMA-aggregated features. Plugging
        # tract-level z-scores into the standardized formula breaks because
        # tract values are at a different scale than the PUMA-level means/
        # stds the standardization was calibrated against; the y_mean
        # intercept then dominates and produces near-uniform within-PUMA
        # allocation regardless of marginal density.
        # Fix: back-transform the standardized coefficients to raw units
        # (β_raw_k = β_std_k / σ_k) and predict pred(t) = Σ β_raw_k · x_k_t
        # directly, with no intercept. This is the share-component of the
        # response — proportional to marginal density — which is exactly
        # what within-PUMA raking needs. The PUMA-level FH+EBLUP machinery
        # still controls absolute totals via raking_target.
        feature_stds = model["feature_stds"]
        coefs = model["coefs"]
        # Back-transform standardized coefficients to raw units for tract-level
        # prediction. β_raw_k = β_std_k / σ_k. Index 0 is population, indices
        # 1..K map onto marginals_list[0..K-1] and marginal_moes[0..K-1].
        coefs_raw = [
            (coefs[k] / feature_stds[k]) if feature_stds[k] > 0 else 0.0
            for k in range(len(coefs))
        ]

        def predict(t: str) -> float:
            raw_features = [tract_pop.get(t, 0.0)] + [
                marg.get(t, 0.0) for marg in marginals_list
            ]
            pred = sum(c * x for c, x in zip(coefs_raw, raw_features))
            return max(pred, 0.0)

        def prediction_se(t: str) -> float:
            """MOE-propagated standard error of predict(t).

            For pred(t) = Σ_k β_raw_k · x_k(t), with ACS published 90% MOE on
            each x_k(t) and treating MOEs across distinct ACS table cells as
            independent (standard inverse-variance combination, Cochran 1937;
            Hartung, Knapp & Sinha 2008), the propagated variance is
                Var(pred(t)) = Σ_k β_raw_k² · (MOE_k(t) / 1.645)²
            where 1.645 is the 90%-CI z-score the Census Bureau publishes
            against. Population (k=0) is treated as having zero MOE because
            B01003 is a controlled total in ACS detailed tables.
            """
            if marginal_moes is None or len(marginal_moes) != len(marginals_list):
                return 0.0
            var = 0.0
            for k, moe_dict in enumerate(marginal_moes):
                moe = moe_dict.get(t, float("nan"))
                if not np.isfinite(moe) or moe < 0:
                    continue
                sd_k = moe / ACS_MOE_Z90
                # marginal_moes[k] is the MOE for marginals_list[k], which
                # corresponds to coefs_raw[k + 1] (index 0 is population).
                var += (coefs_raw[k + 1] ** 2) * (sd_k ** 2)
            return float(np.sqrt(max(var, 0.0)))

        # MOE-weighted raking. When MOEs are available for every declared
        # marginal, weight each tract's predicted share by 1/(SE(t)² + ε)
        # before raking to the EBLUP total. Tracts whose marginal cells carry
        # large ACS sampling uncertainty contribute proportionally less to
        # within-PUMA allocation; mass shifts to tracts where the predicted
        # share rests on reliable marginal counts. The PUMA-level FH+EBLUP
        # totals are unchanged. See Cochran (1937) for inverse-variance
        # combination, Spielman & Singleton (2015) for the small-area-
        # classification motivation, and METHODOLOGY.md "Step 4" for the full
        # derivation and citation of the alternative Bayesian-propagation
        # approach that was deliberately not chosen.
        moe_weighted_raking = (
            marginal_moes is not None
            and len(marginal_moes) == len(marginals_list)
            and len(marginals_list) > 0
        )
        # Small ε in 1/(SE² + ε) prevents divide-by-zero for tracts whose
        # marginals all carry zero published MOE (controlled totals). Setting
        # ε = 1.0 means a zero-SE tract receives weight = 1.0 rather than
        # ±∞ relative to the rest of the PUMA; this is a numerical safeguard
        # rather than a substantive choice (it does not pull data-driven
        # estimates toward the noise floor).
        SE_VAR_EPS = 1.0

        for puma, tract_geoids in tracts_by_puma.items():
            puma_score = raking_target(puma)
            if puma_score == 0:
                continue
            raw = {t: predict(t) for t in tract_geoids}
            if moe_weighted_raking:
                weights = {
                    t: 1.0 / (prediction_se(t) ** 2 + SE_VAR_EPS)
                    for t in tract_geoids
                }
                weighted_raw = {t: raw[t] * weights[t] for t in tract_geoids}
            else:
                weighted_raw = raw
            weighted_sum = sum(weighted_raw.values())
            if weighted_sum <= 0:
                share = 1.0 / len(tract_geoids) if tract_geoids else 0
                for t in tract_geoids:
                    cohort_tract_scores[t] = round(puma_score * share, 2)
            else:
                factor = puma_score / weighted_sum
                for t in tract_geoids:
                    if weighted_raw[t] > 0:
                        cohort_tract_scores[t] = round(weighted_raw[t] * factor, 2)

        model["moe_weighted_raking"] = moe_weighted_raking
        if marginal_reliability:
            model["marginal_reliability"] = marginal_reliability
        return sub_id, cohort_tract_scores, model

    # Fallback: equal-weight share-blend, or uniform if no marginals.
    n_marg = len(marginals_list)
    equal_weights = [1.0] * n_marg
    for puma, tract_geoids in tracts_by_puma.items():
        puma_score = cohort_puma_scores.get(puma, 0.0)  # no EBLUP without regression
        if puma_score == 0:
            continue
        if n_marg == 0:
            share = 1.0 / len(tract_geoids) if tract_geoids else 0
            blended = {t: round(puma_score * share, 2) for t in tract_geoids}
        else:
            marginals_per_tract: dict[str, list[float]] = {}
            for t in tract_geoids:
                marginals_per_tract[t] = [
                    marg.get(t, 0.0) for marg in marginals_list
                ]
            blended = _phase1_share_blend(
                puma_score, tract_geoids, marginals_per_tract, equal_weights
            )
        for t, v in blended.items():
            if v > 0:
                cohort_tract_scores[t] = v

    if model:
        fallback_reason = (
            f"loocv_r_squared={model.get('loocv_r_squared'):.3f} below "
            f"threshold {LOOCV_R2_THRESHOLD}"
        )
    elif not marginals_list:
        fallback_reason = "no marginals declared"
    else:
        fallback_reason = (
            "regression failed (insufficient PUMAs or singular matrix)"
        )
    summary = {
        "method": "share-blend",
        "n_marginals": n_marg,
        "marginal_names": marginal_names,
        "fallback_reason": fallback_reason,
        "rejected_model": model,  # preserved for transparency if regression ran
    }
    if marginal_reliability:
        summary["marginal_reliability"] = marginal_reliability
    return sub_id, cohort_tract_scores, summary
