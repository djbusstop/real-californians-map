"""Render the geometry assets the pipeline depends on.

Two outputs:
  1. ``cache/puma_shp/``  - extracted TIGER PUMA shapefile, used by
     build_puma_queen_neighbors and build_puma_centroids in pipeline.py
     (which the scoring service calls at startup).
  2. ``data/tracts_ca.geojson``  - California census tract polygons,
     clipped to the CA land polygon so dots never fall in water. Synced
     into ``web/public/data/`` by ``web/scripts/sync-data`` for the
     MapLibre layer in MapView.

Both are slow to regenerate (TIGER downloads, ~50MB each, plus the
clip step) but rarely change. Run this script when:
  - You're setting up the project on a fresh machine and ``cache/puma_shp/``
    is missing
  - A new TIGER vintage drops and you want to refresh boundaries
  - You deliberately want to refresh the clipped tract geometry

Run from anywhere:
    python3 data-pipeline/scripts/render_geometry.py
or from data-pipeline/:
    python3 scripts/render_geometry.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Make ``pipeline`` importable regardless of CWD. The script lives at
# data-pipeline/scripts/render_geometry.py; pipeline.py is one level up.
_DATA_PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(_DATA_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_PIPELINE_DIR))

from data_prep import fetch_pumas_geojson, fetch_tracts_geojson  # noqa: E402


def main() -> int:
    print("[render_geometry] fetching PUMA boundaries...", flush=True)
    t0 = time.time()
    fetch_pumas_geojson()
    print(
        f"[render_geometry] PUMA geometry ready ({time.time() - t0:.1f}s)",
        flush=True,
    )

    print("[render_geometry] fetching tract boundaries...", flush=True)
    t0 = time.time()
    fetch_tracts_geojson()
    print(
        f"[render_geometry] tract geometry ready ({time.time() - t0:.1f}s)",
        flush=True,
    )

    print("[render_geometry] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
