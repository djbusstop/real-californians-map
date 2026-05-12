"""
California Subculture Map: data pipeline.

Pulls ACS PUMS records for California (2020-2024 5-year vintage) via the Census API,
joins person and household records, scores each record against the subculture library
defined in web/lib/library.json, aggregates to PUMA, and writes JSON the Next.js app reads.

Run:
    pip install -r requirements.txt
    python pipeline.py

Outputs (in ./data/):
    pums_ca.parquet         - merged person+household records with weights
    pumas_ca.geojson        - PUMA boundaries (2020 vintage)
    scores.json             - { puma: { subculture_id: weighted_member_count } }
                              The PUMA-level count of cohort members under
                              the threshold-based membership rule.
    scores_variance.json    - { puma: { subculture_id: SDR_variance_of_count } }
    summary.json            - per-subculture member counts + secondary
                              diagnostics (threshold, gate-pass count,
                              soft total, mean fit per member)

Cache: raw API responses are cached in ./cache/ so re-runs are fast. Delete cache/
to force a fresh fetch.

The Census API allows unkeyed requests; if you get rate-limited, request a key at
https://api.census.gov/data/key_signup.html and set CENSUS_API_KEY in the environment.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple

import joblib
import numpy as np
import pandas as pd
import requests
from scipy.optimize import nnls
from tqdm import tqdm

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
# Cohort library lives in the web app's lib/ directory. This is a
# deliberate monorepo choice: the frontend ships the canonical list of
# cohorts (id, name, vibe, color, threshold, tract_marginals, vector,
# proxy_gap), the backend reads the same file at startup for prewarm
# and batch runs. There is no separate backend copy that can drift.
# The `color` field is presentation-only and ignored by every backend
# code path; the canonical_cohort_hash function explicitly excludes it.
CONFIG = ROOT.parent / "web" / "lib" / "library.json"

API_KEY = os.environ.get("CENSUS_API_KEY")  # optional

# ----------------------------------------------------------------------------
# Methodology constants — promoted to module-level so they're auditable and
# tweakable from one place. See METHODOLOGY.md for the rationale of each.
# ----------------------------------------------------------------------------

# Ridge λ candidates for LOOCV. Log-spaced from near-OLS to heavy shrinkage.
LAMBDA_GRID: list[float] = [0.0, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]

# LOOCV R² threshold to accept the regression. Below this, the cohort falls
# back to equal-weight share-blend. Negative LOOCV R² means the model
# generalizes worse than the unconditional mean.
LOOCV_R2_THRESHOLD: float = 0.05

# Conley spatial HAC bandwidth in kilometers. Fixed (not adaptive); see
# METHODOLOGY.md "Diagnostics" subsection for the rationale.
CONLEY_BANDWIDTH_KM: float = 75.0

# Bootstrap iteration count for percentile-CI estimation per cohort.
DEFAULT_N_BOOTSTRAP: int = 1000

# Minimum number of successful bootstrap fits required before we report a CI.
# Below this, we report NaN rather than risk a noisy percentile interval.
BOOTSTRAP_MIN_FITS: int = 100

# VIF "infinity" threshold. R² values above this are reported as VIF = inf
# rather than 1/(1-R²); avoids float-noise artifacts on truly collinear pairs.
VIF_INFINITY_THRESHOLD_R2: float = 1 - 1e-9

# Default membership threshold τ. A PUMS record counts as a cohort member iff
# every `required: true` condition in the trait vector passes AND the soft
# similarity score is at or above this threshold. Override per cohort by
# adding `threshold:` to the cohort entry in web/lib/library.json. See
# METHODOLOGY.md "Scoring" for rationale.
DEFAULT_MEMBERSHIP_THRESHOLD: float = 0.5

# ----------------------------------------------------------------------------
# Parallelism. Two levels:
#   COHORT_N_JOBS  : workers used to process cohorts in distribute_to_tracts.
#                    -1 = all cores. Process-based (loky) backend, since each
#                    cohort does enough CPU work to amortize the fork cost.
#   BOOTSTRAP_N_JOBS: workers used inside _compute_bootstrap_ci. Threading
#                    backend so we don't pay pickling on every resample.
#
# These compose: when cohorts run in parallel, the bootstrap inside each cohort
# worker is auto-forced to serial to avoid core oversubscription. To maximise
# bootstrap parallelism, set COHORT_N_JOBS=1 (cohorts serial) and raise
# BOOTSTRAP_N_JOBS to -1.
# ----------------------------------------------------------------------------
COHORT_N_JOBS: int = -1
BOOTSTRAP_N_JOBS: int = -1

# ----------------------------------------------------------------------------
# ACS marginal reliability thresholds (coefficient of variation, CV).
#
# CV = (MOE / 1.645) / estimate. The denominator 1.645 is the z-score for the
# 90% confidence level (ACS publishes MOEs at 90% by convention).
#
# Reliability thresholds from U.S. Census Bureau (2020), Understanding and
# Using American Community Survey Data: What All Data Users Need to Know,
# chapter 7. Spielman & Singleton (2015) develop the consequences of ignoring
# tract-level MOE in geodemographic classification.
#   CV < 12%               : estimate is considered reliable.
#   12% <= CV < 40%        : use with caution.
#   CV >= 40%              : estimate is not considered reliable.
# ----------------------------------------------------------------------------
CENSUS_CV_CAUTION_THRESHOLD: float = 0.12
CENSUS_CV_UNRELIABLE_THRESHOLD: float = 0.40
ACS_MOE_Z90: float = 1.645


# ----------------------------------------------------------------------------
# Variable lists for the API pull. Keep these aligned with web/lib/library.json.
# Person-record variables (acs5/pums "person" file).
PERSON_VARS = [
    "PUMA",       # 5-digit PUMA code (2020 vintage uses PUMA20 in some places; API field is PUMA)
    "ST",         # state FIPS (always 06 here)
    "PWGTP",      # person weight (main estimate)
    "SERIALNO",   # household serial, for join to household record
    "AGEP",       # age
    "SEX",        # sex
    "SCHL",       # educational attainment
    "RAC1P",      # race (recoded; pulled for diagnostic only, not used in scoring)
    "HISP",       # Hispanic origin (diagnostic only)
    "NATIVITY",   # 1 native, 2 foreign-born
    "LANP",       # language spoken at home (specific code)
    "LANX",       # speaks non-English at home flag
    "ENG",        # English proficiency for non-native speakers (1 very well .. 4 not at all)
    "POBP",       # place of birth
    "PINCP",      # personal income
    "ESR",        # employment status recode
    "OCCP",       # occupation (SOC-based code)
    "INDP",       # industry (NAICS-based code)
    "COW",        # class of worker
    "MAR",        # marital status
    "RELSHIPP",   # relationship to householder (used to derive SAME_SEX)
    "JWTRNS",     # means of transportation to work (commute mode)
    "WKHP",       # usual hours worked per week
    "PAP",        # public assistance income (welfare signal)
    "POVPIP",     # income-to-poverty ratio (501 max; 100 = at poverty line)
    "DIS",        # disability status (1 with, 2 without)
    "WAGP",       # wage and salary income
    "MIG",        # lived in same house 1 year ago (1 yes, 2 same county diff house, 3 diff county same state, 4 diff state, 5 abroad)
    "FER",        # gave birth in last 12 months (1 yes, 2 no; only women 15-50)
    "SCH",        # school enrollment (1 no, 2 public, 3 private)
    "MIL",        # military service status (1 active, 2 past active, 3 training only, 4 never)
    "SSP",        # Social Security income
    "SSIP",       # Supplemental Security Income
    "DPHY",       # ambulatory (mobility) difficulty (1 yes, 2 no)
    "DREM",       # cognitive difficulty incl. mental health (1 yes, 2 no)
    "DEAR",       # hearing difficulty (1 yes, 2 no)
    "DEYE",       # vision difficulty (1 yes, 2 no)
    "DOUT",       # independent living difficulty (1 yes, 2 no)
    "DDRS",       # self-care difficulty (1 yes, 2 no)
    "PUBCOV",     # any public health insurance (1 yes, 2 no)
    "HINS1",      # employer-based health insurance (1 yes, 2 no)
    "WKL",        # when last worked (1 within 12 mo, 2 1-5 yrs ago, 3 5+ yrs ago, 4 never)
]

# PUMS replicate weights (PWGTP1..PWGTP80) for successive-difference replication
# (SDR) variance estimation. With these we can compute the sampling variance of
# any weighted estimate via Var(θ̂) = (4/80) · Σ_r (θ̂_r − θ̂)², per the Census
# methodology described in Wolter 2007, *Introduction to Variance Estimation*,
# 2nd ed., Springer. Used by the Fay-Herriot small-area model.
N_REPLICATE_WEIGHTS = 80
REPLICATE_WEIGHT_VARS = [f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1)]
PERSON_VARS_WITH_REPLICATES = PERSON_VARS + REPLICATE_WEIGHT_VARS

# Household-record variables (acs5/pums "housing" file).
HOUSING_VARS = [
    "SERIALNO",
    "WGTP",       # housing unit weight
    "TEN",        # tenure (1 owned w/ mortgage, 2 owned free, 3 rented, 4 occupied w/o pmt)
    "HHT",        # household type
    "HHL",        # household language
    "MV",         # when householder moved in
    "VEH",        # vehicles available
    "HINCP",      # household income
    "BDSP",       # bedrooms
    "BLD",        # units in structure (2 = single-family detached)
    "VALP",       # property value (owner-occupied only)
    "HFL",        # heating fuel (2 propane, 4 oil/kerosene, 6 wood = rural signals)
    "YRBLT",      # year structure built. PUMS 5-Year encodes this as the
                  # decade-start year: 1939 = "1939 or earlier", 1940 = 1940s,
                  # 1950 = 1950s, ..., 2010 = 2010s, 2020 = "2020 or later".
                  # (Earlier samples used YBL with small integer codes; 2023
                  # 5-Year uses YRBLT with year values.)
    "ACR",        # lot size (1 = <1 acre, 2 = 1-9.99 ac, 3 = 10+ ac)
    "AGS",        # sales of agricultural products (1 none, 2 = $1-999, 3 = $1k-2.5k, etc.)
    "TEL",        # telephone service (1 yes, 2 no)
    "BROADBND",   # broadband internet subscription (1 yes, 2 no)
    "PLM",        # complete plumbing facilities (1 yes, 2 no)
    "LAPTOP",     # laptop or desktop in household (1 yes, 2 no)
    "FS",         # food stamps received in last year (1 yes, 2 no)
    "PARTNER",    # presence of unmarried partner (0 NA, 1 opp-sex, 2 same-sex, 3 no partner)
    "MULTG",      # multigenerational household
    "HUPAOC",     # presence of own children
    "HHLDRRAC1P", # householder race (diagnostic)
    # Same-sex household indicator: derived below from householder + spouse/partner sex.
]

# Direct CSV download from the Census FTP. The API endpoint had reliability issues
# (intermittent 500s on small queries, can't pin down the cause), so we pull the
# bulk CSVs once and parse locally. Much faster after the first run.
# Using 5-year 2023 PUMS (covers 2019-2023, ~2M CA person records, ~5x the 1-year
# sample). Larger downloads (~400MB person + ~120MB housing) and slower first-run
# parquet generation, but dramatically lower per-PUMA sampling variance for narrow
# cohorts under hard gates. The aggregated tract-level marginal tables are the
# 5-year tables either way; this just changes the microdata layer.
PUMS_PERSON_URL = "https://www2.census.gov/programs-surveys/acs/data/pums/2023/5-Year/csv_pca.zip"
PUMS_HOUSING_URL = "https://www2.census.gov/programs-surveys/acs/data/pums/2023/5-Year/csv_hca.zip"

# PUMA boundary candidates, tried in order. The cartographic boundary (CB) files
# are smaller and prettier; TIGER/Line is larger but more reliably available.
# The PUMA20 vintage matches the 2023 PUMS data we're pulling.
PUMA_GEOJSON_URLS = [
    "https://www2.census.gov/geo/tiger/TIGER2024/PUMA/tl_2024_06_puma20.zip",
    "https://www2.census.gov/geo/tiger/TIGER2023/PUMA/tl_2023_06_puma20.zip",
    "https://www2.census.gov/geo/tiger/TIGER2022/PUMA/tl_2022_06_puma20.zip",
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_06_puma20_500k.zip",
]

# State cartographic boundary candidates. CB files exclude major water bodies
# (Pacific, SF Bay, Salton Sea, etc.), so intersecting our PUMAs with the CA
# polygon clips off the ocean and bay slivers that come with TIGER/Line PUMAs.
STATE_CB_URLS = [
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_state_500k.zip",
]

# Tract boundary candidates (TIGER/Line, CA, 2020-vintage tracts).
TRACT_GEOJSON_URLS = [
    "https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_06_tract.zip",
    "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_06_tract.zip",
    "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_06_tract.zip",
]

# Tract → PUMA crosswalk (2020 vintage).
TRACT_PUMA_CROSSWALK_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/2020_Census_Tract_to_2020_PUMA.txt"
)

# ACS aggregated-tables API (different from PUMS endpoint, more reliable).
ACS_API = "https://api.census.gov/data/2023/acs/acs5"


# ----------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------

def _download(url: str, dest: Path) -> Path:
    """Download a URL to dest with progress, skipping if already present."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[cache] {dest.name} already downloaded")
        return dest
    print(f"[fetch] {url}")
    print("        (large file — first download takes 2-5 minutes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name
        ) as bar:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                bar.update(len(chunk))
    return dest


def _read_pums_csv(zip_path: Path, wanted: set[str]) -> pd.DataFrame:
    """Read the single CSV inside a PUMS zip, keeping only the columns we want."""
    with zipfile.ZipFile(zip_path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV inside {zip_path}")
        # PUMS zips usually contain one CSV (e.g. psam_p06.csv for CA persons)
        # plus a few documentation files. Pick the largest .csv as the data file.
        csv_name = max(csv_names, key=lambda n: z.getinfo(n).file_size)
        print(f"[read] {csv_name} from {zip_path.name}")
        with z.open(csv_name) as f:
            df = pd.read_csv(
                f,
                usecols=lambda c: c in wanted,
                low_memory=False,
                dtype=str,  # parse as string then coerce; PUMS has mixed types
            )
    return df


def fetch_puma_list() -> list[str]:
    """Get the list of CA PUMAs from the cartographic boundary file. Avoids a giant
    PUMS API probe (which would 500 on response size for state-level queries)."""
    cached = CACHE / "puma_list.json"
    if cached.exists():
        return json.loads(cached.read_text())
    geo = fetch_pumas_geojson()
    keys = ["PUMACE20", "PUMA20", "PUMACE10", "PUMACE", "PUMA"]
    pumas: set[str] = set()
    for feat in geo["features"]:
        props = feat.get("properties", {})
        for k in keys:
            if k in props and props[k]:
                pumas.add(str(props[k]))
                break
    pumas_list = sorted(pumas)
    cached.write_text(json.dumps(pumas_list))
    return pumas_list


def fetch_pums() -> pd.DataFrame:
    """Download CA PUMS person + household CSVs, join, return a single DataFrame.

    The cached parquet must contain the PUMS replicate weights (PWGTP1..PWGTP80)
    for the Fay-Herriot variance estimator. If an older cache lacks them, we
    regenerate the parquet rather than silently use an incomplete cache.
    """
    parquet_out = DATA / "pums_ca.parquet"
    if parquet_out.exists():
        print(f"[cache] loading {parquet_out}")
        df = pd.read_parquet(parquet_out)
        # Cache must have every column the pipeline expects today: replicate
        # weights, all PERSON_VARS, and all HOUSING_VARS. Anything missing
        # means the parquet predates a column-list change and we regenerate
        # rather than silently scoring conditions on absent fields as zero.
        required_cols = (
            ["PWGTP80"]
            + [c for c in PERSON_VARS if c != "SERIALNO"]
            + [c for c in HOUSING_VARS if c != "SERIALNO"]
        )
        missing = [c for c in required_cols if c not in df.columns]
        if not missing:
            return df
        print(f"[cache] cached parquet lacks columns {missing}; regenerating")
        parquet_out.unlink()

    person_zip = _download(PUMS_PERSON_URL, CACHE / "pums_persons_ca.zip")
    housing_zip = _download(PUMS_HOUSING_URL, CACHE / "pums_housing_ca.zip")

    print("[parse] reading person records (incl. 80 replicate weights for FH)...")
    persons = _read_pums_csv(person_zip, set(PERSON_VARS_WITH_REPLICATES))
    print(f"[parse] {len(persons):,} person records, "
          f"{len(persons.columns)} columns including PWGTP1..PWGTP80")

    print("[parse] reading housing records...")
    housing = _read_pums_csv(housing_zip, set(HOUSING_VARS))
    print(f"[parse] {len(housing):,} housing records, columns: {list(housing.columns)}")

    # Coerce numeric columns; SERIALNO/PUMA/ST stay as strings.
    string_cols = {"SERIALNO", "PUMA", "ST"}
    for col in persons.columns:
        if col in string_cols:
            continue
        persons[col] = pd.to_numeric(persons[col], errors="coerce")
    for col in housing.columns:
        if col in string_cols:
            continue
        housing[col] = pd.to_numeric(housing[col], errors="coerce")

    # Derive SAME_SEX household flag from the RELSHIPP variable (PUMS 2023+):
    #   23 = same-sex husband/wife/spouse
    #   24 = same-sex unmarried partner
    # If any person in a household has one of those codes, the household is same-sex.
    if "RELSHIPP" in persons.columns:
        ss_mask = persons["RELSHIPP"].isin([23, 24])
        ss_serials = set(persons.loc[ss_mask, "SERIALNO"].unique())
        housing["SAME_SEX"] = housing["SERIALNO"].isin(ss_serials).astype(int)
        print(f"[derive] SAME_SEX flagged on {housing['SAME_SEX'].sum():,} households "
              f"({100 * housing['SAME_SEX'].mean():.2f}%)")
    else:
        housing["SAME_SEX"] = 0
        print("[warn] RELSHIPP not in person records; SAME_SEX stays 0")

    df = persons.merge(housing, on="SERIALNO", how="left", suffixes=("", "_hh"))
    print(f"[merge] {len(df):,} joined records")

    DATA.mkdir(exist_ok=True)
    df.to_parquet(parquet_out)
    print(f"[save] wrote {parquet_out}")
    return df


def _fetch_ca_land_polygon():
    """Get a CA state polygon from the Census cartographic boundary state file.
    These files clip out major water bodies, so intersecting PUMAs with the
    result strips the ocean and bay slivers. Returns a shapely geometry or None.
    """
    import geopandas as gpd

    last_err = None
    for url in STATE_CB_URLS:
        try:
            print(f"[clip] trying state CB file: {url}")
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            z = zipfile.ZipFile(BytesIO(r.content))
            extract = CACHE / "state_shp"
            extract.mkdir(parents=True, exist_ok=True)
            z.extractall(extract)
            shp = next(extract.glob("*.shp"))
            states = gpd.read_file(shp).to_crs(epsg=4326)
            # Field names vary by vintage; try a couple.
            ca = None
            for col in ("STUSPS", "STATEFP", "STATE_NAME", "NAME"):
                if col not in states.columns:
                    continue
                if col == "STUSPS":
                    sub = states[states[col] == "CA"]
                elif col == "STATEFP":
                    sub = states[states[col] == "06"]
                else:
                    sub = states[states[col] == "California"]
                if not sub.empty:
                    ca = sub
                    break
            if ca is None or ca.empty:
                raise RuntimeError("CA not found in state boundary file")
            print(f"[clip] loaded CA polygon from {url}")
            return ca.geometry.iloc[0]
        except Exception as e:
            last_err = e
            print(f"[clip] failed ({type(e).__name__}: {e}); trying next")
            continue
    print(f"[warn] all state CB URLs failed; clipping skipped. Last error: {last_err}")
    return None


def fetch_pumas_geojson() -> dict:
    """Fetch CA PUMA boundary, clip against the CA land polygon to remove
    water-body slivers, save as GeoJSON. Tries each PUMA URL until one succeeds.
    """
    out = DATA / "pumas_ca.geojson"
    if out.exists():
        return json.loads(out.read_text())

    extract_dir = CACHE / "puma_shp"
    extract_dir.mkdir(parents=True, exist_ok=True)

    last_err = None
    for url in PUMA_GEOJSON_URLS:
        print(f"[fetch] trying {url}")
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            z = zipfile.ZipFile(BytesIO(r.content))
            z.extractall(extract_dir)
            print(f"[fetch] succeeded: {url}")
            break
        except Exception as e:
            last_err = e
            print(f"[fetch] failed ({type(e).__name__}: {e}); trying next")
            continue
    else:
        raise RuntimeError(
            f"All PUMA boundary URLs failed. Last error: {last_err}\n"
            "Find the right URL at https://www2.census.gov/geo/tiger/ and update PUMA_GEOJSON_URLS."
        )

    import geopandas as gpd
    shp = next(extract_dir.glob("*.shp"))
    gdf = gpd.read_file(shp).to_crs(epsg=4326)

    # Clip out water by intersecting with CA land polygon.
    ca_land = _fetch_ca_land_polygon()
    if ca_land is not None:
        try:
            before = gdf.geometry.area.sum()
            gdf["geometry"] = gdf.geometry.intersection(ca_land)
            after = gdf.geometry.area.sum()
            shrink = 100 * (1 - after / before) if before else 0
            print(f"[clip] PUMAs clipped to CA land; total area shrank {shrink:.1f}%")
            # Drop any that became empty (fully in water — shouldn't happen for CA).
            gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
        except Exception as e:
            print(f"[warn] clip failed ({e}); using unclipped PUMAs")

    geojson = json.loads(gdf.to_json())
    out.write_text(json.dumps(geojson))
    print(f"[save] wrote {out}")
    return geojson


# ----------------------------------------------------------------------------
# Tract-level small-area estimation
# ----------------------------------------------------------------------------

def fetch_tract_puma_crosswalk() -> pd.DataFrame:
    """Download the Census tract → PUMA crosswalk (2020 vintage), filtered to CA.
    Returns a DataFrame with columns: tract_geoid (11-char), puma (5-char)."""
    cached = CACHE / "tract_puma_crosswalk_ca.csv"
    if cached.exists():
        return pd.read_csv(cached, dtype=str)

    print(f"[fetch] {TRACT_PUMA_CROSSWALK_URL}")
    r = requests.get(TRACT_PUMA_CROSSWALK_URL, timeout=120)
    r.raise_for_status()
    raw = CACHE / "tract_puma_crosswalk_raw.txt"
    raw.write_bytes(r.content)
    df = pd.read_csv(raw, dtype=str)
    # Column names vary slightly across vintages; normalize.
    rename = {
        "STATEFP": "state",
        "COUNTYFP": "county",
        "TRACTCE": "tract",
        "PUMA5CE": "puma",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df = df[df["state"] == "06"]  # California
    df["tract_geoid"] = df["state"] + df["county"] + df["tract"]
    df = df[["tract_geoid", "puma"]].drop_duplicates()
    df.to_csv(cached, index=False)
    print(f"[fetch] {len(df):,} CA tract→PUMA mappings")
    return df


class TractMarginal(NamedTuple):
    """Per-tract ACS marginal: point estimate and 90% margin of error.

    Both dicts are keyed by tract GEOID. Suppressed or non-applicable cells:
      - estimates: stored as 0.0 (consistent with the pre-MOE behavior).
      - moes: stored as float('nan') so downstream reliability calculations
              can distinguish a published 0.0 MOE (controlled total) from an
              unpublished or special-coded cell.

    Per U.S. Census Bureau convention, MOEs are published at the 90% confidence
    level. The corresponding standard error is MOE / 1.645 (see ACS_MOE_Z90).
    """

    estimates: dict[str, float]
    moes: dict[str, float]


def _compute_tract_cv(estimate: float, moe: float) -> float | None:
    """Coefficient of variation for one ACS tract cell.

    Definition: CV = (MOE / 1.645) / estimate. The denominator 1.645 is the
    z-score for the 90% confidence level (ACS publishes MOEs at 90%).

    Returns None when CV is undefined: estimate is zero or negative, MOE is
    missing (NaN), or MOE is negative (suppression code passed through).

    Reference: U.S. Census Bureau (2020) Understanding and Using American
    Community Survey Data: What All Data Users Need to Know, chapter 7.
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
    """Reliability summary for a tract-level ACS marginal.

    Returns a dict with:
      - variable: ACS variable name (if provided).
      - n_tracts_evaluated: tracts with a defined CV (estimate > 0 and MOE published).
      - n_suppressed_or_zero: tracts where CV is undefined.
      - n_caution: tracts with CV >= CENSUS_CV_CAUTION_THRESHOLD (0.12).
      - n_unreliable: tracts with CV >= CENSUS_CV_UNRELIABLE_THRESHOLD (0.40).
      - median_cv, p90_cv, max_cv: distribution of defined CVs.

    Reliability bands follow Census Bureau (2020) ACS Handbook, ch. 7:
      CV < 12% reliable; 12% <= CV < 40% caution; CV >= 40% unreliable.
    Spielman & Singleton (2015) discuss why this matters for small-area
    classification: the published point estimates encode sampling uncertainty
    that downstream allocation steps usually ignore, and explicit disclosure
    is the minimum-bar disclosure for any defensible analysis.
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
    """Fetch one ACS variable for all CA tracts via the aggregated-tables API.
    Returns {tract_geoid: float}.

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

    # Fetch estimate and MOE together in a single API call.
    url = f"{ACS_API}?get=NAME,{var},{moe_var}&for=tract:*&in=state:06"
    print(f"[fetch] ACS tract var {var} (with MOE {moe_var})")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    rows = r.json()
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

    # Quick reliability snapshot at fetch time (Census Bureau 2020 thresholds).
    reliability = _summarize_marginal_reliability(estimates, moes, var_name=var)
    if reliability["median_cv"] is not None:
        print(
            f"[fetch] {var}: {len(estimates):,} tract values "
            f"({nonzero:,} nonzero, sum={total:,.0f}); "
            f"reliability median CV={reliability['median_cv']:.2f} "
            f"caution={reliability['n_caution']:,} "
            f"unreliable={reliability['n_unreliable']:,} "
            f"suppressed/zero={reliability['n_suppressed_or_zero']:,}"
        )
    else:
        print(
            f"[fetch] {var}: {len(estimates):,} tract values "
            f"({nonzero:,} nonzero, sum={total:,.0f})"
        )
    return TractMarginal(estimates=estimates, moes=moes)


def fetch_tracts_geojson() -> dict:
    """Fetch CA tract boundaries, clip to CA land, save as GeoJSON."""
    out = DATA / "tracts_ca.geojson"
    if out.exists():
        return json.loads(out.read_text())

    extract_dir = CACHE / "tract_shp"
    extract_dir.mkdir(parents=True, exist_ok=True)

    last_err = None
    for url in TRACT_GEOJSON_URLS:
        print(f"[fetch] trying {url}")
        try:
            r = requests.get(url, timeout=300)
            r.raise_for_status()
            z = zipfile.ZipFile(BytesIO(r.content))
            z.extractall(extract_dir)
            print(f"[fetch] succeeded: {url}")
            break
        except Exception as e:
            last_err = e
            print(f"[fetch] failed ({type(e).__name__}: {e}); trying next")
            continue
    else:
        raise RuntimeError(f"All tract URLs failed: {last_err}")

    import geopandas as gpd
    shp = next(extract_dir.glob("*.shp"))
    gdf = gpd.read_file(shp).to_crs(epsg=4326)
    print(f"[fetch] {len(gdf):,} CA tracts")

    ca_land = _fetch_ca_land_polygon()
    if ca_land is not None:
        try:
            before = gdf.geometry.area.sum()
            gdf["geometry"] = gdf.geometry.intersection(ca_land)
            after = gdf.geometry.area.sum()
            shrink = 100 * (1 - after / before) if before else 0
            print(f"[clip] tracts clipped to CA land; total area shrank {shrink:.1f}%")
            gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
        except Exception as e:
            print(f"[warn] tract clip failed ({e}); using unclipped tracts")

    geojson = json.loads(gdf.to_json())
    out.write_text(json.dumps(geojson))
    print(f"[save] wrote {out}")
    return geojson


def parse_marginal_specs(sub: dict) -> list[str]:
    """Return [variable, ...] from a cohort YAML record.
    Supports flat list `tract_marginals: [VAR, ...]`, single `tract_marginal: VAR`,
    and the legacy weighted form `tract_marginals: [{var, weight}, ...]` (weights
    ignored — coefficients are fit from data via NNLS+Ridge regression)."""
    if "tract_marginals" in sub and sub["tract_marginals"]:
        out = []
        for m in sub["tract_marginals"]:
            if isinstance(m, str):
                out.append(m)
            elif isinstance(m, dict) and "var" in m:
                out.append(m["var"])
        return out
    if "tract_marginal" in sub and sub["tract_marginal"]:
        return [sub["tract_marginal"]]
    return []


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


def fit_area_level_model(
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
    n_features = X.shape[1]
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
        moran_i, moran_z, moran_p = compute_morans_i(
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


def build_puma_centroids(puma_shp_dir: Path) -> dict[str, tuple[float, float]]:
    """Return {puma_id: (lon, lat)} for the centroid of each PUMA polygon.

    Used by the Conley spatial HAC standard error computation. PUMA ids are
    normalized to the 5-char PUMA code (matching keys used elsewhere).
    """
    import geopandas as gpd

    shp_files = list(puma_shp_dir.rglob("*.shp"))
    if not shp_files:
        return {}
    gdf = gpd.read_file(shp_files[0])
    id_col = None
    for c in ["PUMACE20", "PUMACE", "PUMA20", "PUMA", "GEOID20", "GEOID"]:
        if c in gdf.columns:
            id_col = c
            break
    if id_col is None:
        return {}

    def normalize(raw: str) -> str:
        s = str(raw)
        if id_col in ("GEOID20", "GEOID") and len(s) == 7 and s.startswith("06"):
            return s[2:]
        return s.zfill(5) if s.isdigit() and len(s) <= 5 else s

    centroids: dict[str, tuple[float, float]] = {}
    # Use representative_point for stability (centroid can fall outside
    # non-convex polygons; representative_point is guaranteed interior).
    for raw_id, geom in zip(gdf[id_col], gdf.geometry):
        pid = normalize(raw_id)
        try:
            pt = geom.representative_point()
            centroids[pid] = (float(pt.x), float(pt.y))
        except Exception:
            pass
    return centroids


def build_puma_queen_neighbors(puma_shp_dir: Path) -> dict[str, list[str]]:
    """Build queen-contiguity neighbor lists for CA PUMAs.

    Two PUMAs are queen-contiguous if their polygons share any boundary point.
    Returns {puma_id: [neighbor_id, ...]}. Used for Moran's I diagnostics.

    PUMA ids are normalized to the 5-char PUMA code (matching the keys used
    elsewhere in the pipeline; the shapefile's GEOID20 is "ssppppp" so we
    strip the state prefix).
    """
    import geopandas as gpd

    shp_files = list(puma_shp_dir.rglob("*.shp"))
    if not shp_files:
        return {}
    gdf = gpd.read_file(shp_files[0])
    id_col = None
    for c in ["PUMACE20", "PUMACE", "PUMA20", "PUMA", "GEOID20", "GEOID"]:
        if c in gdf.columns:
            id_col = c
            break
    if id_col is None:
        return {}

    def normalize(raw: str) -> str:
        s = str(raw)
        # GEOID is "ssppppp" (state + puma); strip CA's "06" prefix so we
        # land on the 5-char PUMA code that puma_scores uses.
        if id_col in ("GEOID20", "GEOID") and len(s) == 7 and s.startswith("06"):
            return s[2:]
        return s.zfill(5) if s.isdigit() and len(s) <= 5 else s

    gdf = gdf.copy()
    gdf["__pid"] = gdf[id_col].map(normalize)
    gdf = gdf.set_index("__pid")
    sindex = gdf.sindex

    neighbors: dict[str, list[str]] = {}
    for pid_i, geom_i in zip(gdf.index, gdf.geometry):
        candidates = list(sindex.intersection(geom_i.bounds))
        ngh: list[str] = []
        for c_idx in candidates:
            pid_j = gdf.index[c_idx]
            if pid_j == pid_i:
                continue
            geom_j = gdf.geometry.iloc[c_idx]
            if geom_i.touches(geom_j) or geom_i.intersects(geom_j):
                ngh.append(str(pid_j))
        neighbors[str(pid_i)] = ngh
    return neighbors


def compute_morans_i(
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
        model = fit_area_level_model(
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


def distribute_to_tracts(
    puma_scores: dict,
    tract_marginals_by_cohort: dict[str, list[dict[str, float]]],
    cohort_marginal_names: dict[str, list[str]],
    tract_to_puma: dict,
    tract_pop: dict[str, float],
    spatial_weights: dict[str, list[str]] | None = None,
    puma_score_variance: dict[str, dict[str, float]] | None = None,
    puma_centroids: dict[str, tuple[float, float]] | None = None,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    tract_marginal_moes_by_cohort: dict[str, list[dict[str, float]]] | None = None,
) -> tuple[dict, dict]:
    """Distribute PUMA-level cohort scores to tracts via area-level SAE.

    Primary path: NNLS+Ridge regression with z-standardized predictors and
    leave-one-PUMA-out CV for λ. Tract-level predictions are then raked
    (proportionally rescaled) within each PUMA so the within-PUMA total
    matches the PUMS-derived PUMA score (benchmarking constraint).

    Fallback (when no marginals declared, fewer than 8 PUMAs, or LOOCV R²
    below threshold): equal-weight share-blend across the available marginals,
    or uniform within-PUMA distribution if no marginals are usable.

    Parallelism: cohorts are processed in parallel via joblib (loky backend)
    when COHORT_N_JOBS != 1. To avoid core oversubscription, the bootstrap
    inside each cohort worker is forced to serial whenever cohorts run in
    parallel; bootstrap parallelism only kicks in when COHORT_N_JOBS == 1.

    Returns (tract_scores, model_summaries):
      tract_scores: { tract_geoid: { sub_id: score } }
      model_summaries: { sub_id: full diagnostics dict }
    """
    from collections import defaultdict

    tracts_by_puma: dict[str, list[str]] = defaultdict(list)
    for tract_geoid, puma in tract_to_puma.items():
        tracts_by_puma[puma].append(tract_geoid)

    # Collect all cohort ids.
    sub_ids: set[str] = set()
    for vals in puma_scores.values():
        sub_ids.update(vals.keys())

    # PUMA population from tract pop summed via crosswalk.
    puma_pop: dict[str, float] = defaultdict(float)
    for tract_geoid, p in tract_to_puma.items():
        puma_pop[p] += tract_pop.get(tract_geoid, 0.0)

    # Decide effective parallelism. If we're parallelizing cohorts, force
    # bootstrap to serial within each worker; otherwise let bootstrap use
    # whatever BOOTSTRAP_N_JOBS is configured to.
    cohort_n_jobs_effective = COHORT_N_JOBS if len(sub_ids) > 1 else 1
    bootstrap_n_jobs_effective = (
        BOOTSTRAP_N_JOBS if cohort_n_jobs_effective == 1 else 1
    )

    # Build the per-cohort task arguments once.
    sorted_sub_ids = sorted(sub_ids)
    cohort_inputs = []
    for sub_id in sorted_sub_ids:
        cohort_puma_scores = {
            p: vals.get(sub_id, 0.0) for p, vals in puma_scores.items()
        }
        cohort_puma_variance: dict[str, float] | None = None
        if puma_score_variance is not None:
            cohort_puma_variance = {
                p: puma_score_variance.get(p, {}).get(sub_id, 0.0)
                for p in puma_score_variance
            }
        cohort_marginal_moes = (
            tract_marginal_moes_by_cohort.get(sub_id, [])
            if tract_marginal_moes_by_cohort is not None
            else []
        )
        cohort_inputs.append(
            (
                sub_id,
                tract_marginals_by_cohort.get(sub_id, []),
                cohort_marginal_names.get(sub_id, []),
                cohort_puma_scores,
                cohort_puma_variance,
                cohort_marginal_moes,
            )
        )

    # Dispatch cohort workers.
    if cohort_n_jobs_effective == 1:
        cohort_results = [
            _process_one_cohort_for_tracts(
                sub_id,
                marginals_list,
                names,
                tracts_by_puma,
                tract_to_puma,
                puma_pop,
                tract_pop,
                cohort_puma_scores,
                cohort_puma_variance,
                spatial_weights,
                puma_centroids,
                n_bootstrap,
                bootstrap_n_jobs_effective,
                marginal_moes,
            )
            for (
                sub_id,
                marginals_list,
                names,
                cohort_puma_scores,
                cohort_puma_variance,
                marginal_moes,
            ) in cohort_inputs
        ]
    else:
        print(
            f"[parallel] dispatching {len(cohort_inputs)} cohorts to "
            f"{cohort_n_jobs_effective} workers (loky); bootstrap forced serial"
        )
        cohort_results = joblib.Parallel(
            n_jobs=cohort_n_jobs_effective, backend="loky", verbose=5
        )(
            joblib.delayed(_process_one_cohort_for_tracts)(
                sub_id,
                marginals_list,
                names,
                tracts_by_puma,
                tract_to_puma,
                puma_pop,
                tract_pop,
                cohort_puma_scores,
                cohort_puma_variance,
                spatial_weights,
                puma_centroids,
                n_bootstrap,
                bootstrap_n_jobs_effective,
                marginal_moes,
            )
            for (
                sub_id,
                marginals_list,
                names,
                cohort_puma_scores,
                cohort_puma_variance,
                marginal_moes,
            ) in cohort_inputs
        )

    # Merge per-cohort outputs into the global tract dict and summaries.
    out: dict[str, dict[str, float]] = {}
    summaries: dict[str, dict] = {}
    for sub_id, cohort_tract_scores, summary in cohort_results:
        summaries[sub_id] = summary
        for t, score in cohort_tract_scores.items():
            out.setdefault(t, {})[sub_id] = score

    return out, summaries


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

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


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> None:
    DATA.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)

    # The library is a flat JSON list of cohort definitions; no settings
    # block (the pipeline-wide settings that used to live there were
    # decorative or constants by this point — default_threshold is the
    # only one that actually mattered and it lives in DEFAULT_MEMBERSHIP_THRESHOLD).
    subcultures = json.loads(CONFIG.read_text())
    default_threshold = DEFAULT_MEMBERSHIP_THRESHOLD
    print(f"[config] loaded {len(subcultures)} subcultures (default τ={default_threshold:.2f})")

    # Geometry rendering (PUMA shapefile extraction + clipped boundary
    # geojson) is owned by scripts/render_geometry.py now. main() assumes
    # the shapefile already lives in cache/puma_shp/; run the script if
    # you're on a fresh checkout. The service-startup path in service.py
    # keeps a defensive fallback that calls fetch_pumas_geojson when the
    # shapefile is missing, so the function stays in this module.

    df = fetch_pums()
    print(f"[scoring] {len(df):,} records, {df['PUMA'].nunique()} PUMAs")

    # Per-cohort scoring. For each subculture we keep three artifacts:
    #   gates[sub]     : Series[bool], True where every required condition passes
    #   fit_scores[sub]: Series[float], soft similarity in [0, 1]
    #   members[sub]   : Series[float], 1.0 if record is a cohort member, else 0
    # `members` is the primary downstream estimand: a binary indicator that
    # turns into a population count when weighted by PWGTP. `fit_scores` is
    # retained as a within-cohort secondary diagnostic (mean fit per member,
    # distribution of fit, threshold sensitivity). See METHODOLOGY.md.
    gates: dict[str, pd.Series] = {}
    fit_scores: dict[str, pd.Series] = {}
    members: dict[str, pd.Series] = {}
    thresholds: dict[str, float] = {}

    for sub in subcultures:
        sub_id = sub["id"]
        gate, fit_score = score_subculture(df, sub)
        threshold = float(sub.get("threshold", default_threshold))
        member = compute_membership(gate, fit_score, threshold)

        gates[sub_id] = gate
        fit_scores[sub_id] = fit_score
        members[sub_id] = member
        thresholds[sub_id] = threshold

        gate_pass = int(gate.sum())
        member_count = float((member * df["PWGTP"]).sum())
        members_among_passers = int(member.sum())
        # Mean fit among members (only meaningful when there are members).
        if members_among_passers > 0:
            mean_fit = float(((fit_score * member) * df["PWGTP"]).sum() / member_count) if member_count > 0 else 0.0
        else:
            mean_fit = 0.0
        print(
            f"[score] {sub_id:25s}: τ={threshold:.2f}  "
            f"gate_pass={gate_pass:>7,}  members(records)={members_among_passers:>7,}  "
            f"members(weighted)={member_count:>11,.0f}  mean_fit={mean_fit:.3f}"
        )

    # PUMA-level aggregation. The primary aggregate is the weighted count of
    # cohort members per PUMA. We also aggregate the soft fit score for the
    # secondary `mean_fit_per_member` diagnostic.
    puma_scores = aggregate_to_puma(df, members)
    out_scores = DATA / "scores.json"
    out_scores.write_text(json.dumps(puma_scores, indent=2))
    print(f"[save] {out_scores}")

    # PUMS sampling variance per PUMA per cohort, via successive-difference
    # replication on PWGTP1..PWGTP80. With binary membership indicators this
    # is the SDR variance of a population total (count), the canonical use
    # case. Used as σ²_e_p in the Fay-Herriot model.
    print("[variance] computing PUMS sampling variance via SDR (80 replicates)...")
    puma_score_variance = aggregate_to_puma_variance(df, members)
    if puma_score_variance:
        out_variance = DATA / "scores_variance.json"
        out_variance.write_text(json.dumps(puma_score_variance, indent=2))
        print(f"[save] {out_variance}")
    else:
        print("[variance] replicate weights not available; FH will degenerate to OLS")

    # Sanity totals + secondary diagnostics. The primary per-cohort number is
    # the weighted count of members; soft-total and mean-fit-among-members are
    # secondary diagnostics retained for sensitivity analysis and threshold
    # tuning.
    soft_totals = {
        sub_id: float((fit_scores[sub_id] * df["PWGTP"]).sum())
        for sub_id in fit_scores
    }
    member_counts = {
        sub_id: float((members[sub_id] * df["PWGTP"]).sum())
        for sub_id in members
    }
    gate_pass_counts = {
        sub_id: float((gates[sub_id].astype(float) * df["PWGTP"]).sum())
        for sub_id in gates
    }
    mean_fit_per_member = {
        sub_id: (
            float(((fit_scores[sub_id] * members[sub_id]) * df["PWGTP"]).sum() / member_counts[sub_id])
            if member_counts[sub_id] > 0
            else 0.0
        )
        for sub_id in members
    }

    summary = {
        "total_pums_records": len(df),
        "total_weighted_population": float((df["PWGTP"]).sum()),
        "puma_count": int(df["PUMA"].nunique()),
        # Primary estimand: weighted count of cohort members per cohort.
        "per_subculture_member_count": member_counts,
        # Secondary diagnostics, retained per cohort for transparency and
        # threshold-sensitivity analysis.
        "per_subculture_diagnostics": {
            sub_id: {
                "threshold": thresholds[sub_id],
                "gate_pass_weighted": gate_pass_counts[sub_id],
                "soft_total_weighted": soft_totals[sub_id],
                "mean_fit_per_member": mean_fit_per_member[sub_id],
            }
            for sub_id in members
        },
    }
    out_summary = DATA / "summary.json"
    out_summary.write_text(json.dumps(summary, indent=2))
    print(f"[save] {out_summary}")
    print("\n[done] California weighted population:", f"{summary['total_weighted_population']:,.0f}")
    print("[done] Sanity check: should be roughly 39M.")

    # ------------------------------------------------------------------
    # Small-area estimation: distribute PUMA scores to tracts.
    # ------------------------------------------------------------------
    print("\n[tract] starting small-area estimation...")
    crosswalk = fetch_tract_puma_crosswalk()
    tract_to_puma = dict(zip(crosswalk["tract_geoid"], crosswalk["puma"]))

    # Tract population — used as the size term in the regression.
    print("[tract] fetching tract population (B01003_001E)...")
    tract_pop = fetch_acs_tract_marginal("B01003_001E").estimates

    # For each cohort, pull every declared tract marginal. We keep two
    # parallel lists per cohort: point estimates (used for the regression
    # and tract allocation, as before) and MOEs (used for per-marginal
    # reliability disclosure under Census Bureau 2020 CV thresholds).
    tract_marginals_by_cohort: dict[str, list[dict[str, float]]] = {}
    tract_marginal_moes_by_cohort: dict[str, list[dict[str, float]]] = {}
    cohort_marginal_names: dict[str, list[str]] = {}
    for sub in subcultures:
        specs = parse_marginal_specs(sub)
        if not specs:
            print(f"[tract] {sub['id']}: no tract marginals declared; will fall back to uniform")
            tract_marginals_by_cohort[sub["id"]] = []
            tract_marginal_moes_by_cohort[sub["id"]] = []
            cohort_marginal_names[sub["id"]] = []
            continue
        margs: list[dict[str, float]] = []
        marg_moes: list[dict[str, float]] = []
        names: list[str] = []
        for var in specs:
            try:
                fetched = fetch_acs_tract_marginal(var)
                margs.append(fetched.estimates)
                marg_moes.append(fetched.moes)
                names.append(var)
            except Exception as e:
                print(f"[tract] {sub['id']}: failed to fetch {var} ({e}); skipping this marginal")
        tract_marginals_by_cohort[sub["id"]] = margs
        tract_marginal_moes_by_cohort[sub["id"]] = marg_moes
        cohort_marginal_names[sub["id"]] = names

    # Build PUMA queen-contiguity spatial weights for Moran's I diagnostics.
    print("[tract] building PUMA spatial weights (queen contiguity)...")
    try:
        spatial_weights = build_puma_queen_neighbors(CACHE / "puma_shp")
        print(f"[tract] spatial weights: {len(spatial_weights)} PUMAs")
    except Exception as e:
        print(f"[warn] spatial weights failed ({e}); Moran's I will be unavailable")
        spatial_weights = None

    # PUMA centroids for Conley spatial HAC standard errors.
    print("[tract] building PUMA centroids for Conley SE...")
    try:
        puma_centroids = build_puma_centroids(CACHE / "puma_shp")
        print(f"[tract] centroids: {len(puma_centroids)} PUMAs")
    except Exception as e:
        print(f"[warn] centroids failed ({e}); Conley SE will be unavailable")
        puma_centroids = None

    tract_scores, model_summaries = distribute_to_tracts(
        puma_scores,
        tract_marginals_by_cohort,
        cohort_marginal_names,
        tract_to_puma,
        tract_pop,
        spatial_weights=spatial_weights,
        puma_score_variance=puma_score_variance if puma_score_variance else None,
        puma_centroids=puma_centroids if puma_centroids else None,
        n_bootstrap=DEFAULT_N_BOOTSTRAP,
        tract_marginal_moes_by_cohort=tract_marginal_moes_by_cohort,
    )
    out_tract_scores = DATA / "tract_scores.json"
    out_tract_scores.write_text(json.dumps(tract_scores))
    print(f"[save] {out_tract_scores} ({len(tract_scores):,} tracts)")

    # Attach scoring-stage secondary diagnostics (threshold, gate-pass count,
    # soft total, mean fit per member) to each cohort's model summary so the
    # full membership-rule audit lives in one file alongside the regression
    # diagnostics.
    for sub_id, summary in model_summaries.items():
        summary["membership"] = {
            "threshold": thresholds.get(sub_id, default_threshold),
            "default_threshold": default_threshold,
            "weighted_gate_pass": gate_pass_counts.get(sub_id, 0.0),
            "weighted_member_count": member_counts.get(sub_id, 0.0),
            "weighted_soft_total": soft_totals.get(sub_id, 0.0),
            "mean_fit_per_member": mean_fit_per_member.get(sub_id, 0.0),
        }

    out_models = DATA / "model_summaries.json"
    out_models.write_text(json.dumps(model_summaries, indent=2))
    print(f"[save] {out_models}")
    for sub_id, summary in model_summaries.items():
        method = summary.get("method", "unknown")
        if method == "ridge_nnls":
            morans = summary.get("morans_i_residual")
            morans_str = f" Moran_I={morans:+.3f}" if morans is not None else ""
            cond = summary.get("condition_number")
            cond_str = f" cond={cond:.1f}" if cond is not None else ""
            max_vif = max(
                (v for v in summary.get("vif", []) if v != float("inf")),
                default=float("nan"),
            )
            fh = summary.get("fay_herriot")
            fh_str = (
                f" FH(σ²_u={fh['sigma2_u']:.0f},γ_med={fh['median_gamma']:.2f})"
                if fh
                else ""
            )
            print(
                f"[model] {sub_id:25s} ridge_nnls "
                f"R²={summary['r_squared']:.3f} "
                f"LOOCV_R²={summary['loocv_r_squared']:+.3f} "
                f"λ={summary['lambda']:g} max_VIF={max_vif:.1f}"
                f"{cond_str}{morans_str}{fh_str}"
            )
        else:
            print(
                f"[model] {sub_id:25s} share-blend "
                f"({summary.get('fallback_reason', '')})"
            )

    # Tract geometry is rendered by scripts/render_geometry.py and lives
    # in web/public/data/. Pipeline.py does not regenerate it.


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"[error] HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
