"""Data preparation for the cohort scoring service.

Owns the data-prep layer of the project:

  - PUMS fetching and parquet build. The Census FTP CSVs (person and
    household records for California, ACS 2019-2023 5-Year vintage)
    are downloaded once, joined on SERIALNO, augmented with the
    derived SAME_SEX household flag, and persisted as a single parquet
    artifact (data/pums_ca.parquet, ~210 MB, ~1.85M person records).
  - Geometry helpers. PUMA and tract shapefile readers, the
    tract→PUMA crosswalk, PUMA queen-contiguity neighbours (for
    Moran's I), and PUMA centroids (for Conley spatial HAC).
  - Library reader. The cohort library lives in
    web/lib/library.json; the path constant lives here for the rest
    of the stack to consume.
  - Constants. CACHE / DATA / ROOT paths, the Census URLs,
    DEFAULT_MEMBERSHIP_THRESHOLD.
  - main(). Slim CLI entrypoint that calls fetch_pums() to
    materialise the parquet. Run it once on a fresh checkout, or
    after adding fields to pums_fields.json. No batch cohort scoring
    here; that moved to per-cohort live scoring via service.score_one_cohort.

The other modules in this folder:

  scoring.py    Per-record scoring (operators, gates, fit), threshold-
                based membership, PUMA aggregation with SDR variance.
  sae.py        Small-area estimation: ACS marginal fetching, ridge+NNLS,
                Fay-Herriot EBLUP, Conley spatial HAC, bootstrap CIs,
                Moran's I, MOE-weighted within-PUMA raking.
  service.py    Orchestrator: ServerState (long-lived process state)
                and score_one_cohort (the per-/score-request pipeline).
  server.py     FastAPI HTTP layer.
  pums_fields.py  PUMS field catalog loader (reads web/lib/pums_fields.json).

Run:
    pip install -r requirements.txt
    python data_prep.py

The Census API allows unkeyed requests; if you get rate-limited,
request a key at https://api.census.gov/data/key_signup.html and set
CENSUS_API_KEY in the environment.
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

import numpy as np
import pandas as pd
import requests
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
# Methodology constants.
#
# Statistical / SAE constants (lambda grid, LOOCV threshold, Conley bandwidth,
# bootstrap settings, VIF threshold, ACS CV reliability bands) live in sae.py
# alongside the functions that use them. Pipeline.py owns only the data-prep
# and scoring constants below.
# ----------------------------------------------------------------------------

# Default membership threshold τ. A PUMS record counts as a cohort member iff
# every `required: true` condition in the trait vector passes AND the soft
# similarity score is at or above this threshold. Override per cohort by
# adding `threshold:` to the cohort entry in web/lib/library.json. See
# METHODOLOGY.md "Scoring" for rationale.
DEFAULT_MEMBERSHIP_THRESHOLD: float = 0.5


# Variable lists for the API pull. Kept in pums_fields.py because the
# catalog is large and grows; pipeline.py focuses on logic. Both lists
# are deliberately generous: a field listed here gets loaded into the
# parquet eagerly so a POSTed cohort can reference it without forcing
# a rebuild. See docs/fields.md for the full PUMS catalog with codes.
from pums_fields import (  # noqa: E402
    HOUSING_VARS,
    N_REPLICATE_WEIGHTS,
    PERSON_VARS, # Do we need? If not, why
    PERSON_VARS_WITH_REPLICATES,
    REPLICATE_WEIGHT_VARS, # Do we need? If not not, why?
)

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


def fetch_puma_list() -> list[str]: # We mix _ prefixed functions with unprefixed. Is this done consistently? Should we clean up any inconsistency?
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


def _required_parquet_columns() -> set[str]:
    """Set of columns the cached parquet must contain to be considered
    valid for the running system.

    Composed from two sources:
      - Hardcoded plumbing: SERIALNO (person/housing join), PUMA (group
        key), PWGTP (person weight), WGTP (housing weight), and the
        N_REPLICATE_WEIGHTS SDR replicate weights.
      - Every field referenced by any cohort vector in the library JSON.
        Includes derived fields like SAME_SEX, which is computed during
        fetch_pums and persisted to the parquet. 
        # This last point could be broken out more. I think there is more thinking that could be done about "computed fields".
        # These are an expression of queer mapping, and trying to map the invisible. But are these not recreating the *point* of the vectors?
        # Either, I think it's worth considering if we a) Break these out more cleanly and have their use be more auditable and defensible or
        # b) remove these, and use their values in the vectors. One consideration is does this create any speed gain? If there is a speed gain by computing these,
        # then this could legitimise using them. It also means there would be another editorial layer, and that needs to be recognised. I am leaning towards removing

    PERSON_VARS / HOUSING_VARS deliberately do NOT participate. Those
    lists are a generous catalog of "what fields exist and where to
    read them from"; an entry there that no cohort currently uses is
    legitimate (kept around so a POSTed user cohort can reference it # Is this the best way to describe why it's "kept around"
    without forcing a parquet rebuild). The validation only fails when
    a column the running system actually depends on is missing.
    """
    cols: set[str] = {"SERIALNO", "PUMA", "PWGTP", "WGTP"}
    cols.update(f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1))
    library = json.loads(CONFIG.read_text())
    for cohort in library:
        for cond in cohort.get("vector", []):
            cols.add(cond["field"])
    return cols


def fetch_pums() -> pd.DataFrame:
    """Download CA PUMS person + household CSVs, join, return a single DataFrame.

    The cached parquet must contain the PUMS replicate weights (PWGTP1..PWGTP80)
    for the Fay-Herriot variance estimator. If an older cache lacks them, we
    regenerate the parquet rather than silently use an incomplete cache.

    # I am starting to get a little confused by the data fetching, maybe because it's spread out all over. 
    # I think we could think about the structure and placement of functions within this file.
    # I think the comments are very helpful though!
    # This, after reading, is one of the most important functions. But that's only clear from reading the function
    """
    parquet_out = DATA / "pums_ca.parquet"
    if parquet_out.exists():
        print(f"[cache] loading {parquet_out}")
        df = pd.read_parquet(parquet_out)
        # Validation: the parquet must contain every column the running
        # system actually depends on (cohort library fields + hardcoded
        # plumbing). PERSON_VARS / HOUSING_VARS deliberately don't
        # participate here — see _required_parquet_columns docstring.
        required_cols = _required_parquet_columns()
        missing = sorted(c for c in required_cols if c not in df.columns)
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

    # Looking at this, this really seems like a vector level decision. We can have a frontend way of grouping the required fields.
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

    # I see this is also implemented in the scripts. Maybe a comment saying that. I feel like the structure of the file could be better. Maybe we can consider breaking out in to smaller files.
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
    out = DATA / "pumas_ca.geojson" # Should this be saved as geojson? What is this used for? Is it better to just return the values directly, and let any exporting be used in scripts 
    if out.exists():
        return json.loads(out.read_text())

    extract_dir = CACHE / "puma_shp" # Do we save the pumas_ca and puma_shp to geojson because it's faster to access? Or are we using the file system to manage state that we don't need to manage?
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
    # What exactly is this for? Would be good to explain in a comment
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


def fetch_tracts_geojson() -> dict: # This feels like a weird order for this to be in.
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
    print(f"[save] wrote {out}") # Should this function not worry about writing, and let the script code do that
    return geojson


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




# ----------------------------------------------------------------------------
# NOTE: `distribute_to_tracts` (the multi-cohort batch orchestrator used by
# the old `main()`) was removed when the project shifted to live /score
# per-cohort scoring. service.py calls `_process_one_cohort_for_tracts`
# directly for each request. If batch processing is ever re-introduced,
# the per-cohort function above is the building block; rebuild a
# distribute_to_tracts on top of it. The git history has the prior
# implementation if you need to crib parallel-dispatch boilerplate.
# ----------------------------------------------------------------------------



# ----------------------------------------------------------------------------
# CLI entrypoint
#
# The live /score endpoint is the only consumer of the rest of this module;
# main() exists solely to materialise the PUMS parquet on disk. Run this
# once on a fresh checkout, or after adding fields to pums_fields.json,
# so the FastAPI service has the parquet to load on first boot.
#
# No batch-mode cohort scoring lives here anymore — the project shifted
# to per-cohort scoring at request time (service.score_one_cohort).
# ----------------------------------------------------------------------------


def main() -> None:
    """Build the PUMS parquet artifact from upstream Census CSVs."""
    print("[main] building PUMS parquet...")
    df = fetch_pums()
    print(
        f"[main] done. parquet has {len(df):,} records, "
        f"{df['PUMA'].nunique()} PUMAs, {len(df.columns)} columns."
    )


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(
            f"[error] HTTP {e.response.status_code}: "
            f"{e.response.text[:200]}",
            file=sys.stderr,
        )
        sys.exit(1)

