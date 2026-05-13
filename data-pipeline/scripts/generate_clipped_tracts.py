"""Generate the clipped California census-tract GeoJSON the frontend renders.

Writes ``web/public/data/tracts_ca.geojson``: CA tract polygons loaded
from TIGER, intersected against the CA land polygon so dots never fall
in water, served directly by the MapLibre layer.

Run when:
  - Setting up the project on a fresh machine and
    web/public/data/tracts_ca.geojson is missing
  - A new TIGER vintage drops and you want to refresh tract boundaries
  - You deliberately want to refresh the clipped tract geometry

Run from anywhere:
    python3 data-pipeline/scripts/generate_clipped_tracts.py
or from data-pipeline/:
    python3 scripts/generate_clipped_tracts.py
"""

from __future__ import annotations

import json
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path

import requests
from tqdm import tqdm

# Make data_prep importable regardless of CWD. The script lives at
# data-pipeline/scripts/generate_clipped_tracts.py; data_prep.py is one
# level up.
_DATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(_DATA_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_PIPELINE_DIR))

from data_prep import CACHE  # noqa: E402


# Frontend public assets folder. MapView fetches /data/tracts_ca.geojson
# at runtime, so the file lives at web/public/data/tracts_ca.geojson.
_PROJECT_ROOT = _DATA_PIPELINE_DIR.parent
WEB_PUBLIC_DATA = _PROJECT_ROOT / "web" / "public" / "data"


# Tract boundary candidates (TIGER/Line, CA, 2020-vintage tracts).
_TRACT_GEOJSON_URLS = [
    "https://www2.census.gov/geo/tiger/TIGER2024/TRACT/tl_2024_06_tract.zip",
    "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_06_tract.zip",
    "https://www2.census.gov/geo/tiger/TIGER2022/TRACT/tl_2022_06_tract.zip",
]

# State cartographic boundary candidates. CB files exclude major water
# bodies (Pacific, SF Bay, Salton Sea, etc.), so intersecting tracts
# against the resulting CA polygon strips the ocean and bay slivers
# that come with TIGER/Line tract polygons.
_STATE_CB_URLS = [
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_state_500k.zip",
    "https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_state_500k.zip",
]


def _stream_zip_to_dir(url: str, dest_dir: Path) -> None:
    """GET `url`, stream the response with a tqdm progress bar, and
    unzip to `dest_dir`. Streaming avoids the silent-stall behaviour of
    a buffered requests.get on large TIGER zips."""
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        buf = BytesIO()
        with tqdm(
            total=total, unit="B", unit_scale=True, desc=url.split("/")[-1]
        ) as bar:
            for chunk in r.iter_content(chunk_size=65536):
                buf.write(chunk)
                bar.update(len(chunk))
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            z.extractall(dest_dir)


def _load_tract_shapefile():
    """Download and extract the CA tract shapefile if needed, then return
    an EPSG:4326 GeoDataFrame."""
    extract_dir = CACHE / "tract_shp"
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not any(extract_dir.glob("*.shp")):
        last_err = None
        for url in _TRACT_GEOJSON_URLS:
            print(f"[fetch] trying {url}")
            try:
                _stream_zip_to_dir(url, extract_dir)
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
    print(f"[fetch] {len(gdf):,} CA tracts loaded from shapefile")
    return gdf


def _fetch_ca_land_polygon():
    """Return a shapely geometry for California's land polygon, fetched
    from the Census cartographic boundary state file. CB files exclude
    major water bodies, so the resulting polygon is suitable as a clip
    mask. Returns None if every candidate URL fails (clipping is then
    skipped and we ship the raw TIGER polygons).
    """
    import geopandas as gpd

    last_err = None
    for url in _STATE_CB_URLS:
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
    print(
        f"[warn] all state CB URLs failed; clipping skipped. "
        f"Last error: {last_err}"
    )
    return None


def _render_clipped_tracts_geojson() -> Path:
    gdf = _load_tract_shapefile()

    ca_land = _fetch_ca_land_polygon()
    if ca_land is not None:
        try:
            before = gdf.geometry.area.sum()
            gdf["geometry"] = gdf.geometry.intersection(ca_land)
            after = gdf.geometry.area.sum()
            shrink = 100 * (1 - after / before) if before else 0
            print(
                f"[clip] tracts clipped to CA land; total area shrank "
                f"{shrink:.1f}%"
            )
            gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
        except Exception as e:
            print(f"[warn] tract clip failed ({e}); writing unclipped tracts")

    WEB_PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    out = WEB_PUBLIC_DATA / "tracts_ca.geojson"
    out.write_text(json.dumps(json.loads(gdf.to_json())))
    print(f"[save] wrote {out}")
    return out


def main() -> int:
    print(
        "[generate_clipped_tracts] rendering clipped tract geojson...",
        flush=True,
    )
    t0 = time.time()
    _render_clipped_tracts_geojson()
    print(
        f"[generate_clipped_tracts] done ({time.time() - t0:.1f}s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
