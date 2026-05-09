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
    "PWGTP",      # person weight
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
    """Download CA PUMS person + household CSVs, join, return a single DataFrame."""
    parquet_out = DATA / "pums_ca.parquet"
    if parquet_out.exists():
        print(f"[cache] loading {parquet_out}")
        return pd.read_parquet(parquet_out)

    person_zip = _download(PUMS_PERSON_URL, CACHE / "pums_persons_ca.zip")
    housing_zip = _download(PUMS_HOUSING_URL, CACHE / "pums_housing_ca.zip")

    print("[parse] reading person records...")
    persons = _read_pums_csv(person_zip, set(PERSON_VARS))
    print(f"[parse] {len(persons):,} person records, columns: {list(persons.columns)}")

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


def distribute_to_tracts(
    puma_scores: dict,
    tract_marginals: dict,
    tract_to_puma: dict,
) -> dict:
    """Small-area estimation: distribute PUMA-level subculture scores across tracts
    using each subculture's tract-level marginal as the weight.

    puma_scores: { puma_code: { sub_id: score } }
    tract_marginals: { sub_id: { tract_geoid: marginal_value } }
    tract_to_puma: { tract_geoid: puma_code }

    Returns: { tract_geoid: { sub_id: score } }
    """
    from collections import defaultdict

    # Group tracts under each PUMA.
    tracts_by_puma: dict[str, list[str]] = defaultdict(list)
    for tract_geoid, puma in tract_to_puma.items():
        tracts_by_puma[puma].append(tract_geoid)

    # Collect all subculture ids.
    sub_ids: set[str] = set()
    for vals in puma_scores.values():
        sub_ids.update(vals.keys())

    out: dict[str, dict[str, float]] = {}
    for sub_id in sub_ids:
        marginals = tract_marginals.get(sub_id, {})
        for puma, tract_geoids in tracts_by_puma.items():
            puma_score = puma_scores.get(puma, {}).get(sub_id, 0)
            if puma_score == 0:
                continue
            total_marg = sum(marginals.get(t, 0) for t in tract_geoids)
            if total_marg <= 0:
                # No marginal data for this PUMA's tracts → uniform spread.
                share = 1.0 / len(tract_geoids) if tract_geoids else 0
                for t in tract_geoids:
                    out.setdefault(t, {})[sub_id] = round(puma_score * share, 2)
            else:
                for t in tract_geoids:
                    m = marginals.get(t, 0)
                    if m <= 0:
                        continue
                    share = m / total_marg
                    out.setdefault(t, {})[sub_id] = round(puma_score * share, 2)
    return out


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

    # Pull each subculture's tract-level marginal from the ACS API.
    tract_marginals: dict[str, dict[str, float]] = {}
    for sub in subcultures:
        var = sub.get("tract_marginal")
        if not var:
            print(f"[tract] {sub['id']}: no tract_marginal in YAML; skipping")
            continue
        try:
            tract_marginals[sub["id"]] = fetch_acs_tract_marginal(var)
        except Exception as e:
            print(f"[tract] {sub['id']}: failed to fetch {var} ({e}); will fall back to uniform")
            tract_marginals[sub["id"]] = {}

    tract_scores = distribute_to_tracts(puma_scores, tract_marginals, tract_to_puma)
    out_tract_scores = DATA / "tract_scores.json"
    out_tract_scores.write_text(json.dumps(tract_scores))
    print(f"[save] {out_tract_scores} ({len(tract_scores):,} tracts)")

    fetch_tracts_geojson()


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"[error] HTTP {e.response.status_code}: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
