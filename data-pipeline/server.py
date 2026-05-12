"""FastAPI server exposing the cohort scoring pipeline as an HTTP service.

Implements ``POST /score`` per ``docs/cohort_api_spec.md``. Loads the
expensive pipeline state (PUMS DataFrame, crosswalks, spatial weights,
PUMA centroids, tract-population marginal) once at startup and holds it
in process memory across requests. Per-request work is just the
single-cohort pipeline run (PUMS scoring -> PUMA aggregation -> tract
marginal fetch -> ridge+NNLS -> FH+EBLUP -> bootstrap -> raking) which
is wrapped by ``service.score_one_cohort()``.

Caching:
  - Cohort result cache (disk). Key: 12-hex content hash of the cohort
    definition. One file per cohort (``response_<hash>.json``) holds
    the full response including inline tract_scores. Cache hits read
    this file and return verbatim.
  - Marginal cache (in-process). Held inside the ``ServerState``; reused
    across cohorts within the same process. Survives requests, not
    restarts.

Run with:
    cd data-pipeline
    uvicorn server:app --host 0.0.0.0 --port 8000 --log-level info
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from data_prep import HOUSING_VARS, PERSON_VARS
from service import (
    ServerState,
    canonical_cohort_hash,
    score_one_cohort,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Cache directory for cohort responses. Content-hash keyed, so no
# invalidation is needed; files live indefinitely. One file per cohort
# (``response_<hash>.json``) holds the full response including inline
# tract_scores. Roughly 50-200KB per file; ~100MB at 1000 unique cohorts.
COHORT_CACHE_DIR = Path(__file__).parent / "cohort_cache"

# Known PUMS fields. The set is sourced from data_prep.PERSON_VARS +
# HOUSING_VARS plus derived SAME_SEX. Used for early validation so we
# can return a friendly error before running the pipeline.
KNOWN_FIELDS: set[str] = (
    set(PERSON_VARS) | set(HOUSING_VARS) | {"SAME_SEX"}
)

KNOWN_OPS: set[str] = {
    "eq",
    "in",
    "range",
    "gte",
    "lte",
    "occupation_soc_major",
    "industry_naics",
}

MAX_MARGINALS = 8


# ---------------------------------------------------------------------------
# Pydantic models (request/response schemas)
# ---------------------------------------------------------------------------


class VectorEntry(BaseModel):
    """One condition in a cohort vector. See cohort_api_spec.md §2.4."""

    field: str
    op: str
    value: Any
    weight: float = Field(gt=0)
    required: bool = False

    @field_validator("field")
    @classmethod
    def _validate_field(cls, v: str) -> str:
        # PydanticCustomError sets the error's `type` field to "unknown_field"
        # so the spec error-code mapping in validation_exception_handler can
        # read it directly rather than parsing the message string.
        if v not in KNOWN_FIELDS:
            raise PydanticCustomError(
                "unknown_field",
                "Field '{field}' is not in the known PUMS fields list.",
                {"field": v},
            )
        return v

    @field_validator("op")
    @classmethod
    def _validate_op(cls, v: str) -> str:
        if v not in KNOWN_OPS:
            raise PydanticCustomError(
                "unknown_op",
                "Op '{op}' is not in the known operators list: {known}",
                {"op": v, "known": sorted(KNOWN_OPS)},
            )
        return v


class CohortRequest(BaseModel):
    """POST /score request body. See cohort_api_spec.md §2.2."""

    name: str
    vibe: str
    threshold: float = Field(default=0.5, gt=0, le=1)
    tract_marginals: List[str] = Field(..., min_length=1, max_length=MAX_MARGINALS)
    vector: List[VectorEntry] = Field(..., min_length=1)
    proxy_gap: Optional[str] = None

    @field_validator("vector")
    @classmethod
    def _at_least_one_required_gate(cls, v: list[VectorEntry]) -> list[VectorEntry]:
        if not any(entry.required for entry in v):
            raise PydanticCustomError(
                "no_required_gate",
                "Cohort vector must include at least one condition with "
                "required: true. See METHODOLOGY: every cohort needs at "
                "least one identity gate.",
            )
        return v


class CohortStats(BaseModel):
    """Stats payload. See cohort_api_spec.md §3.3."""

    weighted_member_count: int
    weighted_gate_pass: int
    weighted_soft_total: int
    mean_fit_per_member: float
    concentration_index: float
    n_pumas_nonzero: int
    n_pumas_total: int
    r_squared: Optional[float]
    loocv_r_squared: Optional[float]
    morans_i_residual: Optional[float]
    morans_i_z_score: Optional[float]
    morans_i_p_value: Optional[float]
    residual_std: Optional[float]
    lambda_chosen: Optional[float]
    fay_herriot_median_gamma: Optional[float]
    feature_names: List[str]
    feature_coefs: List[Optional[float]]


class CohortResponse(BaseModel):
    """POST /score success response. See cohort_api_spec.md §3.1.

    ``tract_scores`` is the same nested ``{tract_geoid: {id: score}}``
    shape the batch pipeline writes, so the frontend's multi-cohort
    merge logic handles single-cohort responses verbatim.
    """

    id: str
    name: str
    tract_scores: Dict[str, Dict[str, float]]
    stats: CohortStats


# ---------------------------------------------------------------------------
# Application lifecycle: load ServerState once at startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and hold the long-lived ServerState across requests.

    First-call latency depends on whether parquet caches are warm; with
    warm caches this takes about 5-15 seconds (PUMS DataFrame load +
    crosswalk + tract-population marginal + spatial weights). Cold (first
    run) it can take several minutes due to PUMS CSV downloads.
    """
    COHORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("[server] starting; loading ServerState...")
    app.state.server_state = ServerState.load()
    print("[server] ready")
    yield
    # No teardown needed; process exit releases memory.


app = FastAPI(
    title="California Culture Map cohort scoring API",
    description=(
        "Single-cohort scoring service. POST a cohort definition and "
        "receive tract-level scores plus the raw statistical diagnostics."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Permissive CORS for v1. Tighten in production deployment if the public
# frontend domain is fixed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

COHORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _response_path(cohort_hash: str) -> Path:
    """Disk location of the cached response for a given content hash."""
    return COHORT_CACHE_DIR / f"response_{cohort_hash}.json"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    """Liveness check. Returns 200 once ServerState is loaded."""
    state = getattr(app.state, "server_state", None)
    if state is None:
        raise HTTPException(status_code=503, detail="server state not loaded")
    return {
        "status": "ok",
        "pums_records": len(state.pums_df),
        "marginal_cache_size": len(state.marginal_cache),
    }


@app.post("/score", response_model=CohortResponse)
def score(req: CohortRequest, request: Request) -> CohortResponse:
    """Score a single cohort end-to-end.

    Cache-aware: identical computational inputs (same content hash)
    return the cached response directly from disk. Server-side timing
    is logged for observability but not exposed in the response body.
    """
    t0 = time.time()
    state: ServerState = request.app.state.server_state

    cohort_def = req.model_dump()
    cohort_hash = canonical_cohort_hash(cohort_def)
    cache_file = _response_path(cohort_hash)

    # Cache hit: response file holds everything (id, name, tract_scores,
    # stats). Return verbatim.
    if cache_file.exists():
        prior = json.loads(cache_file.read_text())
        elapsed_ms = int((time.time() - t0) * 1000)
        print(f"[score] hit  {cohort_hash} ({req.name!r}): {elapsed_ms}ms")
        return CohortResponse.model_validate(prior)

    # Cache miss: run the pipeline. The service computes the canonical
    # hash internally too, so the returned id must match the hash we
    # computed above. A mismatch would indicate the two
    # canonical_cohort_hash callers diverged, which is a programming bug
    # that should surface as a 500 rather than be silenced by `python -O`.
    print(f"[score] miss {cohort_hash} ({req.name!r}): running pipeline...")
    result = score_one_cohort(state, cohort_def)
    if result["id"] != cohort_hash:
        raise HTTPException(
            status_code=500,
            detail=(
                f"hash mismatch: server={cohort_hash} "
                f"service={result['id']} — canonical_cohort_hash "
                "diverged between server.py and service.py"
            ),
        )

    # Persist the full response to disk so future cache hits are O(1).
    # Shape matches CohortResponse exactly so we can model_validate the
    # file contents on hit without any reshaping. Best-effort: if the
    # cache directory got removed (e.g. user did `rm -rf cohort_cache/`
    # to invalidate stale entries), we still serve the response and
    # accept that next request will recompute.
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result))
    except OSError as e:
        print(f"[score] warn: cache write failed ({type(e).__name__}: {e}); serving response without persisting")

    elapsed_ms = int((time.time() - t0) * 1000)
    print(
        f"[score] miss {cohort_hash} done: "
        f"{result['stats']['weighted_member_count']:,} members, "
        f"{elapsed_ms / 1000:.1f}s"
    )

    return CohortResponse.model_validate(result)


# ---------------------------------------------------------------------------
# Custom validation error response (matches spec §8.1 body shape)
# ---------------------------------------------------------------------------


# Spec error codes that our custom validators raise via PydanticCustomError.
# These flow through unchanged because Pydantic preserves the `type` field
# we set in the validator. Codes for built-in Pydantic errors (length,
# range, etc.) are mapped in _classify_builtin_error_code below.
_SPEC_CUSTOM_CODES = {"unknown_field", "unknown_op", "no_required_gate"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Reshape Pydantic's default validation error to the spec body shape:
    {error, code, message, field_path}. Picks the first error if multiple
    fired.

    Custom validators raise PydanticCustomError with the spec error code
    as the error type, so for those we just pass the type through.
    Built-in Pydantic errors (e.g., too_short on a list) get mapped via
    _classify_builtin_error_code based on the field path and Pydantic
    error type.
    """
    errors = exc.errors()
    if not errors:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "code": "unknown",
                "message": "Validation failed.",
                "field_path": None,
            },
        )

    first = errors[0]
    field_path = _format_loc(first.get("loc", ()))
    err_type = first.get("type", "")
    msg = first.get("msg", "Validation failed.")

    if err_type in _SPEC_CUSTOM_CODES:
        code = err_type
    else:
        code = _classify_builtin_error_code(err_type, field_path)

    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "code": code,
            "message": msg,
            "field_path": field_path,
        },
    )


def _format_loc(loc: tuple) -> str | None:
    """Convert a Pydantic location tuple like (body, vector, 0, field) into
    the dotted path "vector[0].field" used in the spec error response."""
    parts: list[str] = []
    for p in loc:
        if p == "body":
            continue
        if isinstance(p, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{p}]"
            else:
                parts.append(f"[{p}]")
        else:
            parts.append(str(p))
    return ".".join(parts) if parts else None


def _classify_builtin_error_code(err_type: str, field_path: str | None) -> str:
    """Map Pydantic's built-in error types to spec error codes
    (cohort_api_spec.md §8.1). Used only when the failure did not come
    from one of our PydanticCustomError validators."""
    # Field-path-specific mappings first.
    if field_path == "threshold":
        return "bad_threshold"
    if field_path == "tract_marginals":
        return "bad_marginal_count"
    if field_path == "vector" and err_type in {"too_short", "list_type", "missing"}:
        return "no_vector"
    # Otherwise fall back to a generic code; the message still tells the
    # caller what went wrong.
    return "validation_error"
