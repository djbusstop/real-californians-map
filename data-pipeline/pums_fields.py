"""PUMS field catalog loader.

The catalog itself lives in `web/lib/pums_fields.json` so it can be
consumed by both the Python pipeline and the frontend (LLM context,
chat UI). This module reads the JSON at import time and exposes the
same five module-level names that the rest of the pipeline already
imports.

Exposed names:
    PERSON_VARS                - CSV columns to pull from the person record
    HOUSING_VARS               - CSV columns to pull from the housing record
    N_REPLICATE_WEIGHTS        - count of person-level replicate weights (PWGTP1..PWGTP{N})
    REPLICATE_WEIGHT_VARS      - derived list ['PWGTP1', ..., 'PWGTP{N}']
    PERSON_VARS_WITH_REPLICATES - PERSON_VARS + REPLICATE_WEIGHT_VARS, used for the parquet build

Derived-field handling:
    SAME_SEX is the project's single documented derivation exception. It
    appears in the JSON catalog with `derived: true` so the LLM sees it in
    the field vocabulary, but it is excluded from PERSON_VARS (which is
    the CSV-read column list) because it is not a CSV column. It is
    computed in pipeline.fetch_pums from RELSHIPP codes 23 and 24. See
    METHODOLOGY.md for the derivation policy and its academic basis
    (Census handbook on household-to-person projection; Wolter 2007 on
    SDR variance under clustering; Williams Institute lineage for the
    interpretation).

For full PUMS field definitions and value codes, see the Census PUMS
data dictionary at
https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2019-2023.pdf
"""

from __future__ import annotations

import json
from pathlib import Path

# Catalog lives in the frontend monorepo, same as web/lib/library.json.
# Backend reads it cross-boundary, identical pattern to pipeline.py's
# library load.
CATALOG_PATH = Path(__file__).parent.parent / "web" / "lib" / "pums_fields.json"

with CATALOG_PATH.open() as f:
    _CATALOG = json.load(f)

# Replicate-weight count drives both the SDR variance formula
# Var = (4/N) * Σ_r (θ̂_r − θ̂)² and the column-name derivation below.
N_REPLICATE_WEIGHTS: int = _CATALOG["n_replicate_weights"]
REPLICATE_WEIGHT_VARS: list[str] = [
    f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1)
]

# PERSON_VARS / HOUSING_VARS are the CSV-read column lists. Derived
# fields (currently only SAME_SEX) are excluded because they are not
# CSV columns; they are computed downstream in pipeline.fetch_pums and
# persisted to the parquet.
PERSON_VARS: list[str] = [
    v["name"] for v in _CATALOG["person_vars"] if not v.get("derived")
]
HOUSING_VARS: list[str] = [
    v["name"] for v in _CATALOG["housing_vars"] if not v.get("derived")
]

# Used by the parquet build when reading the person CSV.
PERSON_VARS_WITH_REPLICATES: list[str] = PERSON_VARS + REPLICATE_WEIGHT_VARS
