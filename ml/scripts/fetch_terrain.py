"""
Phase 1, step 3: terrain features per village (elevation, slope, local relief).

Source: Open-Meteo elevation API (free, no key; Copernicus 90 m elevation data).
Input : ml/data/villages.csv
Output: ml/data/village_static.csv
        village_id, elevation_m, slope_deg, mean_slope_deg, relief_m

How it works
  For each village we sample a 5 x 5 grid of points around it, ~275 m apart
  (so the grid covers about 1.1 km x 1.1 km). From those heights:
    elevation_m     height at the village point
    slope_deg       steepness at the village point (from its 4 neighbours)
    mean_slope_deg  average steepness over the whole grid area
    relief_m        highest minus lowest point in the grid (hilly vs flat)

Run from the project root:
    python ml/scripts/fetch_terrain.py
build_features.py picks up village_static.csv automatically.
"""
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
ML_DIR = Path(__file__).resolve().parents[1]
VILLAGES_CSV = ML_DIR / "data" / "villages.csv"
OUT_FILE = ML_DIR / "data" / "village_static.csv"

GRID = 9              # 9 x 9 points per village
STEP_DEG = 0.005      # ~550 m between points (grid covers ~4.4 km)
MAX_PER_REQUEST = 100  # API limit on coordinates per call


def get_elevations(lats: list[float], lons: list[float]) -> list[float]:
    """Heights in metres for many points, batched and retried."""
    heights: list[float] = []
    for i in range(0, len(lats), MAX_PER_REQUEST):
        params = {
            "latitude": ",".join(f"{x:.5f}" for x in lats[i:i + MAX_PER_REQUEST]),
            "longitude": ",".join(f"{x:.5f}" for x in lons[i:i + MAX_PER_REQUEST]),
        }
        for attempt in range(1, 5):
            try:
                resp = requests.get(ELEVATION_URL, params=params, timeout=60)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} server busy")
                resp.raise_for_status()
                break
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as err:
                if attempt == 4:
                    raise
                print(f"  retry {attempt}/3 in {5 * attempt}s ({err})")
                time.sleep(5 * attempt)
        heights.extend(resp.json()["elevation"])
        time.sleep(1)
    return heights


def slope_grid(z: np.ndarray, lat: float) -> np.ndarray:
    """Slope in degrees at each interior grid point (central differences)."""
    dy = STEP_DEG * 111_320                              # metres per step north-south
    dx = STEP_DEG * 111_320 * math.cos(math.radians(lat))  # east-west shrinks with latitude
    dz_dy = (z[2:, 1:-1] - z[:-2, 1:-1]) / (2 * dy)
    dz_dx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))


def main() -> None:
    villages = pd.read_csv(VILLAGES_CSV)
    offsets = (np.arange(GRID) - GRID // 2) * STEP_DEG

    # Build every grid point for every village, then fetch them in batches.
    all_lats, all_lons = [], []
    for v in villages.itertuples(index=False):
        for dlat in offsets:          # row = north-south
            for dlon in offsets:      # column = east-west
                all_lats.append(v.lat + dlat)
                all_lons.append(v.lon + dlon)

    print(f"fetching {len(all_lats)} elevation points for {len(villages)} villages...")
    heights = np.array(get_elevations(all_lats, all_lons), dtype=float)

    rows = []
    per_village = GRID * GRID
    centre = GRID // 2
    for i, v in enumerate(villages.itertuples(index=False)):
        z = heights[i * per_village:(i + 1) * per_village].reshape(GRID, GRID)
        slopes = slope_grid(z, v.lat)
        rows.append({
            "village_id": v.village_id,
            "elevation_m": round(z[centre, centre], 1),
            "slope_deg": round(slopes[centre - 1, centre - 1], 2),
            "mean_slope_deg": round(slopes.mean(), 2),
            "p90_slope_deg": round(float(np.percentile(slopes, 90)), 2),
            "max_slope_deg": round(slopes.max(), 2),
            "relief_m": round(z.max() - z.min(), 1),
        })
        r = rows[-1]
        print(f"  {v.village_id} {v.name:<12} elev {r['elevation_m']:>6} m  "
              f"slope {r['slope_deg']:>5}°  mean slope {r['mean_slope_deg']:>5}°  "
              f"max slope {r['max_slope_deg']:>5}°  relief {r['relief_m']:>6} m")

    pd.DataFrame(rows).to_csv(OUT_FILE, index=False)
    print(f"saved {OUT_FILE.relative_to(ML_DIR.parent)}")


if __name__ == "__main__":
    main()