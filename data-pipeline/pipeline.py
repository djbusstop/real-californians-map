"""
California Subculture Map: data pipeline.

Pulls ACS PUMS records for California (2020-2024 5-year vintage) via the Census API,
joins person and household records, scores each record against the subculture library
defined in subcultures.yaml, aggregates to PUMA, and writes JSON the Next.js app reads.

Run:
    pip install -r requirements.txt
    python pipeline.py

Outputs (in ./data/):
    pums_ca.parquet         - merged person+household records with weights
    pumas_ca.geojson        - PUMA boundaries (2020 vintage)
    scores.json             - { puma: { subculture_id: weighted_population } }
    summary.json            - per-subculture totals + sanity checks

Cache: raw API responses are cached in ./cache/ so re-runs are fast. Delete cache/
to force a fresh fetch.

The Census API allows unkeyed requests; if you get rate-limited, request a key at
https://api.census.gov/data/key_signup.html and set CENSUS_API_KEY in the environment.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml
from tqdm import tqdm

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
CONFIG = ROOT / "subcultures.yaml"

API_KEY = os.environ.get("CENSUS_API_KEY")  # optional

# ----------------------------------------------------------------------------
# Variable lists for the API pull. Keep these aligned with subcultures.yaml.
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
    "YBL",        # year structure built (1 = 1939 or earlier, 5 = 1970s, etc.)
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
# Using 1-year 2023 PUMS for v0 — smaller download (~80MB person + ~25MB housing),
# ~390k person records, plenty for similarity scoring at PUMA level.
# Switch to /5-Year/ paths if you want the larger 2019-2023 sample later.
PUMS_PERSON_URL = "https://www2.census.gov/programs-surveys/acs/data/pums/2023/1-Year/csv_pca.zip"
PUMS_HOUSING_URL = "https://www2.census.gov/programs-surveys/acs/data/pums/2023/1-Year/csv_hca.zip"

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
        if "PWGTP80" in df.columns:
            return df
        print("[cache] cached parquet lacks replicate weights; regenerating")
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


def fetch_acs_tract_marginal(var: str) -> dict:
    """Fetch one ACS variable for all CA tracts via the aggregated-tables API.
    Returns {tract_geoid: float}.
    """
    cached = CACHE / f"acs_tract_{var}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    url = f"{ACS_API}?get=NAME,{var}&for=tract:*&in=state:06"
    print(f"[fetch] ACS tract var {var}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    rows = r.json()
    header, *data = rows
    state_idx = header.index("state")
    county_idx = header.index("county")
    tract_idx = header.index("tract")
    var_idx = header.index(var)
    out: dict[str, float] = {}
    for row in data:
        geoid = row[state_idx] + row[county_idx] + row[tract_idx]
        try:
            out[geoid] = float(row[var_idx]) if row[var_idx] not in (None, "") else 0.0
        except (TypeError, ValueError):
            out[geoid] = 0.0
    cached.write_text(json.dumps(out))
    print(f"[fetch] {var}: {len(out):,} tract values, sum={sum(out.values()):,.0f}")
    return out


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
    import warnings
    import numpy as np
    from scipy.optimize import nnls

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
    import numpy as np

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
    import numpy as np

    synthetic = X @ beta
    direct_residual = y - synthetic
    denom = sigma2_u + sigma2_e
    gamma = np.where(denom > 0, sigma2_u / denom, 0.0)
    eblup = synthetic + gamma * direct_residual
    return eblup, gamma


def _compute_conley_se(X_z, residuals, lam, puma_ids, centroids, bandwidth_km=75.0):
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
    import numpy as np

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

    XtX_lam_inv = np.linalg.pinv(X_z.T @ X_z + lam * np.eye(p))
    V = XtX_lam_inv @ X_z.T @ Omega @ X_z @ XtX_lam_inv
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    return [float(s) for s in se]


def _compute_bootstrap_ci(
    Xz, y_centered, lam, n_bootstrap=1000, alpha=0.05, seed=42
):
    """Non-parametric percentile bootstrap confidence intervals for ridge+NNLS
    coefficients (Efron & Tibshirani 1993, *An Introduction to the Bootstrap*).

    Resamples PUMAs with replacement n_bootstrap times, refits the same
    ridge+NNLS model at fixed λ on each resample, and returns the (α/2, 1-α/2)
    percentile interval per coefficient.

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
    import numpy as np

    rng = np.random.default_rng(seed)
    n, p = Xz.shape
    coef_samples = np.zeros((n_bootstrap, p))

    for b in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        coefs_b = _fit_ridge_nnls(Xz[idx], y_centered[idx], lam)
        if coefs_b is None:
            coef_samples[b] = np.nan
        else:
            coef_samples[b] = coefs_b

    # Drop any failed fits before computing percentiles.
    mask = ~np.isnan(coef_samples).any(axis=1)
    coef_samples = coef_samples[mask]
    if len(coef_samples) < 100:
        return [float("nan")] * p, [float("nan")] * p

    lower = np.percentile(coef_samples, 100 * alpha / 2, axis=0)
    upper = np.percentile(coef_samples, 100 * (1 - alpha / 2), axis=0)
    return [float(x) for x in lower], [float(x) for x in upper]


def _compute_vifs(Xz):
    """Variance Inflation Factors for each column of standardized design matrix Xz.
    VIF_j = 1 / (1 - R²_j) where R²_j is the R² from regressing column j on the rest.
    VIF > 10 conventionally indicates problematic multicollinearity (Belsley et al. 1980).
    """
    import numpy as np

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
            vifs.append(float(1.0 / (1.0 - r2_j)) if r2_j < 0.9999 else float("inf"))
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
    n_bootstrap: int = 1000,
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
    import numpy as np

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

    # Cross-validate ridge λ by leave-one-PUMA-out.
    # Log-spaced grid covers regimes from near-OLS (λ≈0) to heavy shrinkage.
    lam_grid = [0.0, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
    n_obs = Xz.shape[0]
    cv_scores: dict[float, float] = {}
    best_lam = 0.0
    best_loocv = -float("inf")

    for lam in lam_grid:
        loo_preds = np.zeros(n_obs)
        for i in range(n_obs):
            mask = np.ones(n_obs, dtype=bool)
            mask[i] = False
            coefs_i = _fit_ridge_nnls(Xz[mask], y_centered[mask], lam)
            if coefs_i is None:
                loo_preds[i] = y_mean
            else:
                loo_preds[i] = float(Xz[i] @ coefs_i + y_mean)
        ss_res_loo = float(np.sum((y - loo_preds) ** 2))
        ss_tot = float(np.sum((y - y_mean) ** 2))
        loocv_r2 = 1 - ss_res_loo / ss_tot if ss_tot > 0 else 0.0
        cv_scores[lam] = loocv_r2
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
            Xz, y_centered, best_lam, n_bootstrap=n_bootstrap
        )

    return {
        "method": "ridge_nnls",
        "n_pumas": int(n_obs),
        "lambda": float(best_lam),
        "lambda_cv_grid": {f"{k:g}": float(v) for k, v in cv_scores.items()},
        "feature_names": feature_names,
        "coefs": [float(c) for c in coefs],
        "feature_means": [float(m) for m in X_means],
        "feature_stds": [float(s) for s in X_stds],
        "y_mean": float(y_mean),
        "r_squared": float(r_squared),
        "loocv_r_squared": float(best_loocv),
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
    import numpy as np
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


def distribute_to_tracts(
    puma_scores: dict,
    tract_marginals_by_cohort: dict[str, list[dict[str, float]]],
    cohort_marginal_names: dict[str, list[str]],
    tract_to_puma: dict,
    tract_pop: dict[str, float],
    spatial_weights: dict[str, list[str]] | None = None,
    puma_score_variance: dict[str, dict[str, float]] | None = None,
    puma_centroids: dict[str, tuple[float, float]] | None = None,
    n_bootstrap: int = 1000,
) -> tuple[dict, dict]:
    """Distribute PUMA-level cohort scores to tracts via area-level SAE.

    Primary path: NNLS+Ridge regression with z-standardized predictors and
    leave-one-PUMA-out CV for λ. Tract-level predictions are then raked
    (proportionally rescaled) within each PUMA so the within-PUMA total
    matches the PUMS-derived PUMA score (benchmarking constraint).

    Fallback (when no marginals declared, fewer than 8 PUMAs, or LOOCV R²
    below threshold): equal-weight share-blend across the available marginals,
    or uniform within-PUMA distribution if no marginals are usable.

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

    out: dict[str, dict[str, float]] = {}
    summaries: dict[str, dict] = {}

    # LOOCV R² threshold to accept the regression. Negative LOOCV means the
    # model generalizes worse than the mean — we fall back to share-blend.
    LOOCV_THRESHOLD = 0.05

    for sub_id in sorted(sub_ids):
        marginals_list = tract_marginals_by_cohort.get(sub_id, [])
        names = cohort_marginal_names.get(sub_id, [])
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

        cohort_puma_scores = {
            p: vals.get(sub_id, 0.0) for p, vals in puma_scores.items()
        }

        # Per-PUMA sampling variance for this cohort (FH input).
        cohort_puma_variance: dict[str, float] | None = None
        if puma_score_variance is not None:
            cohort_puma_variance = {
                p: puma_score_variance.get(p, {}).get(sub_id, 0.0)
                for p in puma_score_variance
            }

        # ── Try regression ──
        model = None
        if marginals_list:
            print(f"[fit] {sub_id}: ridge+NNLS with FH+Conley+bootstrap...")
            model = fit_area_level_model(
                cohort_puma_scores,
                puma_pop,
                puma_marginals,
                names,
                spatial_weights=spatial_weights,
                puma_score_variance=cohort_puma_variance,
                puma_centroids=puma_centroids,
                n_bootstrap=n_bootstrap,
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

        if model and model.get("loocv_r_squared", -1) >= LOOCV_THRESHOLD:
            # Predict tract-level raw counts, then rake within each PUMA.
            feature_means = model["feature_means"]
            feature_stds = model["feature_stds"]
            coefs = model["coefs"]
            y_mean = model["y_mean"]

            def predict(t: str) -> float:
                # Build standardized feature vector: [pop, M_1, ..., M_K]
                raw_features = [tract_pop.get(t, 0.0)] + [
                    marg.get(t, 0.0) for marg in marginals_list
                ]
                z_pred = y_mean
                for k, x_k in enumerate(raw_features):
                    s = feature_stds[k]
                    if s > 0:
                        z_pred += coefs[k] * (x_k - feature_means[k]) / s
                return max(z_pred, 0.0)

            for puma, tract_geoids in tracts_by_puma.items():
                puma_score = raking_target(puma)
                if puma_score == 0:
                    continue
                raw = {t: predict(t) for t in tract_geoids}
                raw_sum = sum(raw.values())
                if raw_sum <= 0:
                    share = 1.0 / len(tract_geoids) if tract_geoids else 0
                    for t in tract_geoids:
                        out.setdefault(t, {})[sub_id] = round(puma_score * share, 2)
                else:
                    factor = puma_score / raw_sum
                    for t in tract_geoids:
                        if raw[t] > 0:
                            out.setdefault(t, {})[sub_id] = round(raw[t] * factor, 2)
            summaries[sub_id] = model
        else:
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
                        out.setdefault(t, {})[sub_id] = v
            if model:
                fallback_reason = (
                    f"loocv_r_squared={model.get('loocv_r_squared'):.3f} below "
                    f"threshold {LOOCV_THRESHOLD}"
                )
            elif not marginals_list:
                fallback_reason = "no marginals declared"
            else:
                fallback_reason = (
                    "regression failed (insufficient PUMAs or singular matrix)"
                )
            summaries[sub_id] = {
                "method": "share-blend",
                "n_marginals": n_marg,
                "marginal_names": names,
                "fallback_reason": fallback_reason,
                "rejected_model": model,  # preserved for transparency if regression ran
            }

    return out, summaries


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

def _eval_condition(df: pd.DataFrame, cond: dict) -> pd.Series:
    """Returns a 0..1 Series indicating how well each row satisfies the condition."""
    if cond.get("computed") == "modal":
        # Special-cased upstream.
        return pd.Series(0.0, index=df.index)
    field = cond["field"]
    if field not in df.columns:
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


def score_subculture(df: pd.DataFrame, sub: dict) -> pd.Series:
    """Compute a similarity score per record for one subculture.
    Required conditions act as gates (return 0 if not satisfied).
    Other conditions sum weighted contributions, normalized to 0..1.
    """
    if sub["id"] == "normie":
        return _score_normie(df)

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
        return pd.Series(0.0, index=df.index)
    score = score / weight_total
    return score.where(gate, 0.0)


def _score_normie(df: pd.DataFrame) -> pd.Series:
    """Normie = similarity to the modal trait combination across all CA records.
    For v0, approximate by computing the mode of a few key traits and scoring on match."""
    keys = ["AGEP", "TEN", "HHT", "MAR", "SCHL"]
    # Bucket age into decades for "mode" purposes.
    df = df.copy()
    df["AGEP_BUCKET"] = (df["AGEP"] // 10) * 10
    keys = ["AGEP_BUCKET", "TEN", "HHT", "MAR", "SCHL"]
    modes = {k: df[k].mode().iloc[0] for k in keys if k in df.columns}
    score = pd.Series(0.0, index=df.index)
    for k, v in modes.items():
        score += (df[k] == v).astype(float)
    score = score / len(modes) if modes else score
    return score


def aggregate_to_puma(df: pd.DataFrame, scores: dict[str, pd.Series]) -> dict:
    """Weight scores by person weight (PWGTP), sum per PUMA, and return:
    { puma_code: { subculture_id: weighted_population_score } }
    """
    out: dict[str, dict[str, float]] = {}
    for sub_id, score in scores.items():
        weighted = score * df["PWGTP"]
        per_puma = weighted.groupby(df["PUMA"]).sum()
        for puma, val in per_puma.items():
            out.setdefault(str(puma), {})[sub_id] = round(float(val), 1)
    return out


def aggregate_to_puma_variance(
    df: pd.DataFrame, scores: dict[str, pd.Series]
) -> dict[str, dict[str, float]]:
    """Compute the sampling variance of each PUMA-level cohort estimate via
    the Census-published successive-difference replication (SDR) formula:

        Var(θ̂) = (4/80) · Σ_r (θ̂_r − θ̂)²

    where θ̂ uses the main weight PWGTP and θ̂_r uses replicate weight PWGTPr.
    Reference: Wolter 2007, *Introduction to Variance Estimation*, 2nd ed.,
    Springer, §3.7; Census Bureau, *PUMS Accuracy of the Data* (2023).

    Returns: { puma_code: { subculture_id: sampling_variance_of_score } }.
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

    for sub_id, score in scores.items():
        # Main estimate per PUMA.
        main_per_puma = (score * df["PWGTP"]).groupby(puma_index).sum()
        # 80 replicate estimates per PUMA.
        rep_per_puma = pd.DataFrame(index=main_per_puma.index)
        for r_col in rep_cols:
            rep_per_puma[r_col] = (score * df[r_col]).groupby(puma_index).sum()
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

    config = yaml.safe_load(CONFIG.read_text())
    subcultures = config["subcultures"]
    print(f"[config] loaded {len(subcultures)} subcultures")

    # Boundaries first — needed to discover PUMA codes before chunked PUMS pulls.
    fetch_pumas_geojson()

    df = fetch_pums()
    print(f"[scoring] {len(df):,} records, {df['PUMA'].nunique()} PUMAs")

    scores = {}
    for sub in subcultures:
        s = score_subculture(df, sub)
        scores[sub["id"]] = s
        print(f"[score] {sub['id']:25s}: avg={s.mean():.3f} max={s.max():.3f} nonzero={(s > 0).sum():,}")

    puma_scores = aggregate_to_puma(df, scores)
    out_scores = DATA / "scores.json"
    out_scores.write_text(json.dumps(puma_scores, indent=2))
    print(f"[save] {out_scores}")

    # PUMS sampling variance per PUMA per cohort, via successive-difference
    # replication on PWGTP1..PWGTP80. Used as σ²_e_p in the Fay-Herriot model.
    print("[variance] computing PUMS sampling variance via SDR (80 replicates)...")
    puma_score_variance = aggregate_to_puma_variance(df, scores)
    if puma_score_variance:
        out_variance = DATA / "scores_variance.json"
        out_variance.write_text(json.dumps(puma_score_variance, indent=2))
        print(f"[save] {out_variance}")
    else:
        print("[variance] replicate weights not available; FH will degenerate to OLS")

    # Sanity totals.
    summary = {
        "total_pums_records": len(df),
        "total_weighted_population": float((df["PWGTP"]).sum()),
        "puma_count": int(df["PUMA"].nunique()),
        "per_subculture_weighted_total": {
            sub_id: float((scores[sub_id] * df["PWGTP"]).sum()) for sub_id in scores
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
    tract_pop = fetch_acs_tract_marginal("B01003_001E")

    # For each cohort, pull every declared tract marginal.
    tract_marginals_by_cohort: dict[str, list[dict[str, float]]] = {}
    cohort_marginal_names: dict[str, list[str]] = {}
    for sub in subcultures:
        specs = parse_marginal_specs(sub)
        if not specs:
            print(f"[tract] {sub['id']}: no tract marginals declared; will fall back to uniform")
            tract_marginals_by_cohort[sub["id"]] = []
            cohort_marginal_names[sub["id"]] = []
            continue
        margs: list[dict[str, float]] = []
        names: list[str] = []
        for var in specs:
            try:
                margs.append(fetch_acs_tract_marginal(var))
                names.append(var)
            except Exception as e:
                print(f"[tract] {sub['id']}: failed to fetch {var} ({e}); skipping this marginal")
        tract_marginals_by_cohort[sub["id"]] = margs
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
        n_bootstrap=1000,
    )
    out_tract_scores = DATA / "tract_scores.json"
    out_tract_scores.write_text(json.dumps(tract_scores))
    print(f"[save] {out_tract_scores} ({len(tract_scores):,} tracts)")

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

    fetch_tracts_geojson()


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"[error] HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
