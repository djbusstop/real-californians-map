"""Unit tests for service.py.

Covers pure functions that do not require ServerState (hash, Gini,
value normalization). The end-to-end scoring is exercised separately
by tests/_smoke_latency.py against the loaded pipeline state.

Run with:
    cd data-pipeline && python3 -m pytest tests/test_service.py -v
or:
    cd data-pipeline && python3 -m unittest tests.test_service -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make ``service`` importable when invoked from anywhere.
_DATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(_DATA_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_PIPELINE_DIR))

from service import (  # noqa: E402
    _normalize_value,
    canonical_cohort_hash,
    compute_gini,
)


def _base_cohort() -> dict:
    """A small, valid cohort definition used as the starting point for
    most hash-stability tests."""
    return {
        "name": "test",
        "vibe": "test vibe",
        "threshold": 0.5,
        "tract_marginals": ["B01001_001E"],
        "vector": [
            {
                "field": "AGEP",
                "op": "gte",
                "value": 18,
                "weight": 1,
                "required": True,
            }
        ],
    }


class TestCanonicalCohortHash(unittest.TestCase):
    """Verify the hash treats cosmetic differences as equivalent and
    semantic differences as distinct, per cohort_api_spec.md §2.5."""

    def test_name_does_not_affect_hash(self):
        a = _base_cohort()
        b = {**a, "name": "different name"}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_vibe_does_not_affect_hash(self):
        a = _base_cohort()
        b = {**a, "vibe": "different vibe"}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_proxy_gap_does_not_affect_hash(self):
        a = _base_cohort()
        b = {**a, "proxy_gap": "this is a documentation field only"}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_vector_entry_order_does_not_affect_hash(self):
        a = _base_cohort()
        a["vector"] = [
            {"field": "AGEP", "op": "gte", "value": 18, "weight": 1, "required": True},
            {"field": "SEX", "op": "eq", "value": 1, "weight": 2, "required": True},
        ]
        b = {**a, "vector": list(reversed(a["vector"]))}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_tract_marginal_order_does_not_affect_hash(self):
        a = _base_cohort()
        a["tract_marginals"] = ["B01001_001E", "B25024_002E"]
        b = {**a, "tract_marginals": ["B25024_002E", "B01001_001E"]}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_duplicate_tract_marginals_collapsed(self):
        a = _base_cohort()
        b = {**a, "tract_marginals": ["B01001_001E", "B01001_001E"]}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_in_value_order_does_not_affect_hash(self):
        """`in` is order-insensitive — [1,2,3] and [3,2,1] mean the same
        thing. _normalize_value sorts these before hashing."""
        a = _base_cohort()
        a["vector"] = [
            {"field": "RAC1P", "op": "in", "value": [1, 2, 3], "weight": 1, "required": True}
        ]
        b = {**a, "vector": [
            {"field": "RAC1P", "op": "in", "value": [3, 2, 1], "weight": 1, "required": True}
        ]}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_in_value_duplicates_collapsed(self):
        a = _base_cohort()
        a["vector"] = [
            {"field": "RAC1P", "op": "in", "value": [1, 2], "weight": 1, "required": True}
        ]
        b = {**a, "vector": [
            {"field": "RAC1P", "op": "in", "value": [1, 2, 2, 1], "weight": 1, "required": True}
        ]}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_range_value_order_is_significant(self):
        """`range` is positional — [25, 65] and [65, 25] are NOT equivalent."""
        a = _base_cohort()
        a["vector"] = [
            {"field": "AGEP", "op": "range", "value": [25, 65], "weight": 1, "required": True}
        ]
        b = {**a, "vector": [
            {"field": "AGEP", "op": "range", "value": [65, 25], "weight": 1, "required": True}
        ]}
        self.assertNotEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_required_false_is_equivalent_to_absent(self):
        a = _base_cohort()
        # Two non-required (soft) entries: one with required:false, one without.
        a["vector"].append(
            {"field": "TEN", "op": "eq", "value": 1, "weight": 0.5, "required": False}
        )
        b = {**a, "vector": [
            a["vector"][0],
            {"field": "TEN", "op": "eq", "value": 1, "weight": 0.5},
        ]}
        self.assertEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_threshold_change_affects_hash(self):
        a = _base_cohort()
        b = {**a, "threshold": 0.7}
        self.assertNotEqual(canonical_cohort_hash(a), canonical_cohort_hash(b))

    def test_hash_length_is_12_hex(self):
        h = canonical_cohort_hash(_base_cohort())
        self.assertEqual(len(h), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


class TestNormalizeValue(unittest.TestCase):
    def test_in_sorted_and_deduped(self):
        self.assertEqual(_normalize_value("in", [3, 1, 2, 1]), [1, 2, 3])

    def test_occupation_soc_major_sorted(self):
        self.assertEqual(
            _normalize_value("occupation_soc_major", [27, 21, 25]),
            [21, 25, 27],
        )

    def test_industry_naics_sorted(self):
        self.assertEqual(
            _normalize_value("industry_naics", [62, 51, 54]),
            [51, 54, 62],
        )

    def test_range_left_unchanged(self):
        self.assertEqual(_normalize_value("range", [25, 65]), [25, 65])
        # Even if "wrong", we don't reorder a range — it's positional.
        self.assertEqual(_normalize_value("range", [65, 25]), [65, 25])

    def test_eq_left_unchanged(self):
        self.assertEqual(_normalize_value("eq", 1), 1)

    def test_gte_left_unchanged(self):
        self.assertEqual(_normalize_value("gte", 80000), 80000)


class TestComputeGini(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(compute_gini([]), 0.0)

    def test_all_zeros_returns_zero(self):
        self.assertEqual(compute_gini([0, 0, 0, 0]), 0.0)

    def test_uniform_returns_zero(self):
        self.assertEqual(compute_gini([10, 10, 10, 10]), 0.0)

    def test_fully_concentrated_approaches_one(self):
        # Single non-zero value among many zeros: Gini approaches (n-1)/n.
        self.assertGreater(compute_gini([0, 0, 0, 100]), 0.7)

    def test_bounded_in_range(self):
        for vals in [[0, 0, 0, 1], [1, 2, 3, 4, 5], [100, 1, 1, 1], [50, 50, 50, 1]]:
            with self.subTest(vals=vals):
                g = compute_gini(vals)
                self.assertGreaterEqual(g, 0.0)
                self.assertLessEqual(g, 1.0)

    def test_none_values_skipped(self):
        # None entries should be filtered out, leaving a valid computation.
        self.assertEqual(compute_gini([10, None, 10, None]), 0.0)

    def test_negative_values_skipped(self):
        # Defensive: negative EBLUPs would be a bug upstream, but if they
        # appear we don't want them poisoning the Gini.
        self.assertEqual(compute_gini([-5, 10, 10, 10]), 0.0)


if __name__ == "__main__":
    unittest.main()
