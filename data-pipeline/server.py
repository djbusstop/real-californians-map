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
    definition. Two files written per cohort: the tract_scores JSON
    served at the URL the frontend fetches, and a response sidecar JSON
    containing the full response so a cache hit can return without
    re-running the pipeline.
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
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from pipeline import HOUSING_VARS, PERSON_VARS
from service import (
    ServerState,
    canonical_cohort_hash,
    score_one_cohort,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Cache directory for cohort results. Files written here are served via
# the static mount below and live indefinitely (content-hash keyed, so
# no invalidation needed). Roughly 50-200KB per cohort; ~100MB at 1000
# unique cohorts.
COHORT_CACHE_DIR = Path(__file__).parent / "cohort_cache"

# Static URL path under which cohort tract-scores files are served.
# A request comes back from POST /score with a tract_scores_url like
# "/cohorts/tract_scores_<hash>.json" that the frontend fetches.
COHORT_URL_PREFIX = "/cohorts"

# Known PUMS fields. The set is sourced from pipeline.PERSON_VARS +
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
    tract_marginals: list[str] = Field(..., min_length=1, max_length=MAX_MARGINALS)
    vector: list[VectorEntry] = Field(..., min_length=1)
    proxy_gap: str | None = None

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
    r_squared: float | None
    loocv_r_squared: float | None
    morans_i_residual: float | None
    morans_i_z_score: float | None
    morans_i_p_value: float | None
    residual_std: float | None
    lambda_chosen: float | None
    fay_herriot_median_gamma: float | None
    feature_names: list[str]
    feature_coefs: list[float | None]
    marginal_reliability_summary: str


class CohortResponse(BaseModel):
    """POST /score success response. See cohort_api_spec.md §3.1."""

    cohort_id: str
    tract_scores_url: str
    stats: CohortStats
    cache_status: Literal["hit", "miss"]
    elapsed_ms: int


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
        "receive tract-level scores plus the raw statistical diagnostics "
        "the LLM uses for interpretive conversation."
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

# Serve cohort_cache/ at /cohorts/* so the frontend can fetch the
# tract-scores JSON files referenced in the response's tract_scores_url.
# StaticFiles validates directory existence at import time, so ensure
# the cache directory exists before mounting (the lifespan handler will
# also ensure this at startup, but it runs after module import).
COHORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    COHORT_URL_PREFIX,
    StaticFiles(directory=str(COHORT_CACHE_DIR)),
    name="cohort_cache",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tract_scores_path(cohort_hash: str) -> Path:
    return COHORT_CACHE_DIR / f"tract_scores_{cohort_hash}.json"


def _response_sidecar_path(cohort_hash: str) -> Path:
    return COHORT_CACHE_DIR / f"response_{cohort_hash}.json"


def _tract_scores_url(cohort_hash: str) -> str:
    return f"{COHORT_URL_PREFIX}/tract_scores_{cohort_hash}.json"


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

    Cache-aware: identical computational inputs (same content hash) skip
    the pipeline and return the prior response from the disk sidecar.
    """
    t0 = time.time()
    state: ServerState = request.app.state.server_state

    cohort_def = req.model_dump()
    cohort_hash = canonical_cohort_hash(cohort_def)

    # Cache hit path: prior identical request already has tract scores and
    # response sidecar on disk. Return the sidecar verbatim, only updating
    # cache_status and elapsed_ms.
    sidecar = _response_sidecar_path(cohort_hash)
    tract_file = _tract_scores_path(cohort_hash)
    if sidecar.exists() and tract_file.exists():
        prior = json.loads(sidecar.read_text())
        prior["cache_status"] = "hit"
        prior["elapsed_ms"] = int((time.time() - t0) * 1000)
        prior["tract_scores_url"] = _tract_scores_url(cohort_hash)
        return CohortResponse.model_validate(prior)

    # Cache miss: run the pipeline. The service computes the canonical
    # hash internally too, so the returned cohort_id must match the hash
    # we computed above. A mismatch would indicate the two
    # canonical_cohort_hash callers diverged, which is a programming bug
    # that should surface as a 500 rather than be silenced by `python -O`.
    print(f"[score] miss {cohort_hash} ({req.name!r}): running pipeline...")
    result = score_one_cohort(state, cohort_def)
    if result["cohort_id"] != cohort_hash:
        raise HTTPException(
            status_code=500,
            detail=(
                f"hash mismatch: server={cohort_hash} "
                f"service={result['cohort_id']} — canonical_cohort_hash "
                "diverged between server.py and service.py"
            ),
        )

    # Persist tract scores in the spec's nested {tract: {cohort_id: score}}
    # shape. Frontend's existing merge logic handles this verbatim.
    tract_file.write_text(json.dumps(result["tract_scores"]))

    # Build and persist the response sidecar so future cache hits are O(1).
    response_dict = {
        "cohort_id": cohort_hash,
        "tract_scores_url": _tract_scores_url(cohort_hash),
        "stats": result["stats"],
        "cache_status": "miss",
        "elapsed_ms": result["elapsed_ms"],
    }
    sidecar.write_text(json.dumps(response_dict))

    print(
        f"[score] miss {cohort_hash} done: "
        f"{result['stats']['weighted_member_count']:,} members, "
        f"{result['elapsed_ms']/1000:.1f}s"
    )

    return CohortResponse.model_validate(response_dict)


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
