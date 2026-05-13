"""Generate per-cohort JSON files for the web frontend.

For each cohort in web/lib/library.json, write a static snapshot of its
/score response to web/public/data/cohorts/<library_id>.json. The
frontend reads these files directly at request time; the live FastAPI
service is not on the runtime path.

Resolution order per cohort:

  1. Compute the canonical content hash via service.canonical_cohort_hash.
  2. If data-pipeline/cohort_cache/response_<hash>.json already exists,
     use it. The disk cache is already a complete /score response.
  3. Otherwise call service.score_one_cohort() directly, in-process,
     and persist the result. ServerState is loaded lazily on the
     first miss; if every cohort hits cache, the heavy load is
     skipped entirely.

The script and the live FastAPI service share the same scoring code
path and the same on-disk cohort_cache, so a result generated either
way is bit-identical.

Run from anywhere:
    python3 data-pipeline/scripts/generate_cohort_files.py
or from data-pipeline/:
    python3 scripts/generate_cohort_files.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the service module importable regardless of CWD.
_DATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(_DATA_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_PIPELINE_DIR))

from service import (  # noqa: E402
    ServerState,
    canonical_cohort_hash,
    score_one_cohort,
)

_PROJECT_ROOT = _DATA_PIPELINE_DIR.parent
LIBRARY_PATH = _PROJECT_ROOT / "web" / "lib" / "library.json"
COHORT_CACHE_DIR = _DATA_PIPELINE_DIR / "cohort_cache"
OUT_DIR = _PROJECT_ROOT / "web" / "public" / "data" / "cohorts"


class _LazyServerState:
    """One-shot lazy holder for ServerState. The actual load is
    expensive (PUMS parquet + ACS marginal fetches + spatial weights);
    we only pay it if at least one cohort cache-misses."""

    def __init__(self) -> None:
        self._state: ServerState | None = None

    def get(self) -> ServerState:
        if self._state is None:
            print("[generate] cache miss — loading ServerState (one-time cost)")
            self._state = ServerState.load()
        return self._state


def main() -> int:
    library = json.loads(LIBRARY_PATH.read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lazy_state = _LazyServerState()

    hits = 0
    misses_filled = 0

    print(f"[generate] library: {LIBRARY_PATH}")
    print(f"[generate] cache:   {COHORT_CACHE_DIR}")
    print(f"[generate] out:     {OUT_DIR}")
    print(f"[generate] {len(library)} cohorts")
    print()

    for cohort in library:
        library_id = cohort["id"]
        # The library cohort dict is passed straight to the scoring
        # functions. canonical_cohort_hash and score_one_cohort only
        # read threshold / tract_marginals / vector / name; any other
        # fields (color, the library's own id) are silently ignored.
        cohort_hash = canonical_cohort_hash(cohort)
        cache_file = COHORT_CACHE_DIR / f"response_{cohort_hash}.json"

        if cache_file.exists():
            print(f"[hit ] {library_id:30s} {cohort_hash}")
            payload = json.loads(cache_file.read_text())
            hits += 1
        else:
            print(f"[miss] {library_id:30s} {cohort_hash} → score_one_cohort")
            state = lazy_state.get()
            payload = score_one_cohort(state, cohort)
            # Persist into the cohort_cache so future runs of this
            # script (and any live service started from the same
            # working directory) short-circuit at the cache check.
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(payload))
            misses_filled += 1

        # Override the response's `name` with the library cohort's own
        # name. Two library cohorts can theoretically collide on
        # content hash; the cache file then carries whichever name was
        # scored first. We want each per-id output file to advertise
        # the library cohort's own name.
        payload["name"] = cohort["name"]

        out_file = OUT_DIR / f"{library_id}.json"
        out_file.write_text(json.dumps(payload))
        print(f"        wrote {out_file.relative_to(_PROJECT_ROOT)}")

    print()
    print(f"[generate] done: {hits} cache hits, {misses_filled} fresh scores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
