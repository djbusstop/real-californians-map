"""Data preparation for the cohort scoring service.

Owns the data-prep layer of the project:

  - PUMS fetching and parquet build. The Census FTP CSVs (person and
    household records for California, ACS 2019-2023 5-Year vintage)
    are downloaded once, joined on SERIALNO, augmented with the
    derived SAME_SEX household flag, and persisted as a single parquet
    artifact (cache/pums_ca.parquet, ~210 MB, ~1.85M person records).
  - Geometry helpers. PUMA and tract shapefile readers, the
    tract→PUMA crosswalk, PUMA queen-contiguity neighbours (for
    Moran's I), and PUMA centroids (for Conley spatial HAC).
  - Library reader. The cohort library lives in
    web/lib/library.json; the path constant lives here for the rest
    of the stack to consume.
  - PUMS field catalog. PERSON_VARS, HOUSING_VARS, N_REPLICATE_WEIGHTS
    derived from pums_fields.yaml at import time.
  - main(). Slim CLI entrypoint that calls fetch_pums() to
    materialise the parquet. Run it once on a fresh checkout, or
    after adding fields to pums_fields.yaml.

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
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
import yaml
from tqdm import tqdm

ROOT = Path(__file__).parent
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
# Constants. Scoring constants (membership threshold) live in scoring.py;
# SAE constants (lambda grid, Conley bandwidth, bootstrap settings) live
# in sae.py.
# ----------------------------------------------------------------------------

# PUMS field catalog. Loaded from pums_fields.yaml at import time. The lists
# are deliberately generous: a field in the YAML gets loaded into the parquet
# eagerly so a POSTed cohort can reference it without forcing a rebuild.
# Derived fields (currently only SAME_SEX) are computed in fetch_pums and are
# not enumerated in the YAML; see METHODOLOGY.md "Field derivation policy".
_PUMS_FIELDS_YAML = ROOT / "pums_fields.yaml"
with _PUMS_FIELDS_YAML.open() as _f:
    _CATALOG = yaml.safe_load(_f)

# Replicate-weight count drives both the SDR variance formula
# Var = (4/N) * Σ_r (θ̂_r − θ̂)² and the column-name derivation below.
N_REPLICATE_WEIGHTS: int = _CATALOG["n_replicate_weights"]
REPLICATE_WEIGHT_VARS: list[str] = [
    f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1)
]
PERSON_VARS: list[str] = list(_CATALOG["person_vars"])
HOUSING_VARS: list[str] = list(_CATALOG["housing_vars"])
PERSON_VARS_WITH_REPLICATES: list[str] = PERSON_VARS + REPLICATE_WEIGHT_VARS

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


# Naming convention in this module: a leading underscore marks an
# internal helper (private to data_prep.py), no underscore marks a
# function imported elsewhere in the stack (service.py, scripts, etc.).
def _required_parquet_columns() -> set[str]:
    """Set of columns the cached parquet must contain to be considered
    valid for the running system.

    The parquet must have every catalog field (PERSON_VARS + HOUSING_VARS),
    the derived SAME_SEX flag (METHODOLOGY.md "Field derivation policy"),
    the join/group/weight plumbing, and the N_REPLICATE_WEIGHTS SDR
    replicate weights. server.py's request validator builds its
    KNOWN_FIELDS set from PERSON_VARS + HOUSING_VARS + SAME_SEX, so a
    user-authored cohort that names any of those fields must find them
    in the loaded DataFrame; if the YAML catalog grows but the parquet
    predates the addition, the validation fails here and fetch_pums
    rebuilds.
    """
    cols: set[str] = {"SERIALNO", "PUMA", "PWGTP", "WGTP", "SAME_SEX"}
    cols.update(f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1))
    cols.update(PERSON_VARS)
    cols.update(HOUSING_VARS)
    return cols


def fetch_pums() -> pd.DataFrame:
    """Download CA PUMS person + household CSVs, join, return a single DataFrame.

    The cached parquet must contain the PUMS replicate weights (PWGTP1..PWGTP80)
    for the Fay-Herriot variance estimator. If an older cache lacks them, we
    regenerate the parquet rather than silently use an incomplete cache.
    """
    parquet_out = CACHE / "pums_ca.parquet"
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

    CACHE.mkdir(exist_ok=True)
    df.to_parquet(parquet_out)
    print(f"[save] wrote {parquet_out}")
    return df




def load_puma_shapefile():
    """Download and extract the CA PUMA shapefile if needed, then return
    an EPSG:4326 GeoDataFrame.

    The shapefile under cache/puma_shp/ is what build_puma_centroids
    and build_puma_queen_neighbors read at service startup, so the
    extract is on the scoring path's critical resource list. Tries
    each PUMA URL until one succeeds; skips the network if the
    shapefile is already extracted.
    """
    extract_dir = CACHE / "puma_shp"
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not any(extract_dir.glob("*.shp")):
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
                "Find the right URL at https://www2.census.gov/geo/tiger/ "
                "and update PUMA_GEOJSON_URLS."
            )

    import geopandas as gpd
    shp = next(extract_dir.glob("*.shp"))
    return gpd.read_file(shp).to_crs(epsg=4326)


# ----------------------------------------------------------------------------
# Tract-level small-area estimation
# ----------------------------------------------------------------------------

def fetch_tract_puma_crosswalk() -> pd.DataFrame:
    """Download the Census tract → PUMA crosswalk (2020 vintage), filtered to CA.

    Returns a DataFrame with columns: tract_geoid (11-char), puma (5-char).

    The crosswalk is what lets the SAE step move between scales: cohort
    estimates are computed per PUMA (because PUMS records carry a PUMA
    id, not a tract id), then distributed down to tracts using
    ACS-published tract-level marginals plus the within-PUMA tract
    structure this crosswalk supplies. service.ServerState builds two
    derived dicts from it at startup: tract→PUMA and PUMA→[tracts].
    """
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
# CLI entrypoint
# ----------------------------------------------------------------------------


def main() -> None:
    """Build the PUMS parquet artifact from upstream Census CSVs.

    Run on a fresh checkout, or after adding fields to pums_fields.yaml,
    so the FastAPI service has the parquet to load on first boot.
    """
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

