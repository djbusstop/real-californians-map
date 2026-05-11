"""Smoke / latency test for the single-cohort scoring service.

Runs ServerState.load() then scores a known cohort (queer_leftist) and
times each phase. Prints a summary and exits 0 on PASS, 1 on MISS.

Run from anywhere:
    python3 data-pipeline/tests/smoke_latency.py
or from data-pipeline/:
    python3 tests/smoke_latency.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Make ``service`` and ``pipeline`` importable regardless of CWD. This
# file lives at data-pipeline/tests/smoke_latency.py; the modules it
# needs live in data-pipeline/ (one level up).
_DATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(_DATA_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_PIPELINE_DIR))

import yaml  # noqa: E402

from service import ServerState, score_one_cohort  # noqa: E402


SUBCULTURES_YAML = _DATA_PIPELINE_DIR / "subcultures.yaml"
LATENCY_TARGET_S = 60.0
TEST_COHORT_ID = "queer_leftist"


def main() -> int:
    print("=== Loading ServerState ===", flush=True)
    t0 = time.time()
    state = ServerState.load()
    t_load = time.time() - t0
    print(f"ServerState load: {t_load:.1f}s", flush=True)
    print(flush=True)

    config = yaml.safe_load(SUBCULTURES_YAML.read_text())
    try:
        test_cohort = next(
            s for s in config["subcultures"] if s["id"] == TEST_COHORT_ID
        )
    except StopIteration:
        print(
            f"ERROR: cohort {TEST_COHORT_ID!r} not in {SUBCULTURES_YAML}; "
            f"either move to a branch that has it or change TEST_COHORT_ID.",
            file=sys.stderr,
        )
        return 2

    print("=== Cold run ===", flush=True)
    t0 = time.time()
    result = score_one_cohort(state, test_cohort)
    t_cold = time.time() - t0
    print(f"TOTAL cold: {t_cold:.1f}s", flush=True)
    print(f"cohort_id: {result['cohort_id']}", flush=True)
    print(
        f"weighted_member_count: {result['stats']['weighted_member_count']:,}",
        flush=True,
    )
    print(
        f"concentration_index: {result['stats']['concentration_index']}",
        flush=True,
    )
    print(
        f"loocv_r_squared: {result['stats']['loocv_r_squared']}",
        flush=True,
    )
    print(
        f"n_pumas_nonzero: {result['stats']['n_pumas_nonzero']}/"
        f"{result['stats']['n_pumas_total']}",
        flush=True,
    )
    print(f"tract_scores entries: {len(result['tract_scores'])}", flush=True)
    print(flush=True)

    print("=== Warm run (same cohort, marginal cache hot) ===", flush=True)
    t0 = time.time()
    result2 = score_one_cohort(state, test_cohort)
    t_warm = time.time() - t0
    print(f"TOTAL warm: {t_warm:.1f}s", flush=True)
    print(
        f"hash match: {result['cohort_id'] == result2['cohort_id']}",
        flush=True,
    )
    print(flush=True)

    print("=== Latency target ===", flush=True)
    print(f"Target: under {LATENCY_TARGET_S:.0f}s per cohort", flush=True)
    cold_pass = t_cold < LATENCY_TARGET_S
    warm_pass = t_warm < LATENCY_TARGET_S
    print(f"Cold: {t_cold:.1f}s -> {'PASS' if cold_pass else 'MISS'}", flush=True)
    print(f"Warm: {t_warm:.1f}s -> {'PASS' if warm_pass else 'MISS'}", flush=True)
    return 0 if (cold_pass and warm_pass) else 1


if __name__ == "__main__":
    sys.exit(main())
