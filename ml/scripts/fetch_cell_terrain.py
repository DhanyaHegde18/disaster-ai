"""
How steep each rain-grid square is: landslides need slopes, so the model needs to know.

Source : Copernicus DEM GLO-90 (90 m elevation map of the whole world), free under the Copernicus licence,
         hosted on AWS Open Data (no account needed). Karnataka needs about 40 tiles of 1 x 1 degree,
         roughly 200-300 MB in total, downloaded once into ml/data/raw/dem/ (re-runs reuse them).
         Sea-only tiles don't exist (the download skips them).
For each ~27 km square, slope is computed at EVERY 90 m pixel inside it, then summarised:
  slope_p90     90th percentile slope (degrees): "how steep are its steep parts"
  steep_share   share of land steeper than 25 degrees
  relief        1st to 99th percentile elevation range (m), ignoring single odd pixels
  elev_mean     average land elevation (m)
Sea and lakes (elevation 0 or below, or no data) are left out.
Output : ml/data/cell_terrain.csv

Run from the project root:
    pip install rasterio
    python ml/scripts/fetch_cell_terrain.py
"""
import csv
import math
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
VILLAGES = ROOT / "ml" / "data" / "karnataka_villages.csv"
OUT = ROOT / "ml" / "data" / "cell_terrain.csv"
DEM_DIR = ROOT / "ml" / "data" / "raw" / "dem"
BASE = "https://copernicus-dem-90m.s3.amazonaws.com"
HALF = 0.125                    # a rain-grid square is 0.25 degrees wide
STEEP_DEG = 25.0
FIELDS = ["cell_id", "slope_p90", "steep_share", "relief", "elev_mean"]


def tile_name(lat0: int, lon0: int) -> str:
    """Tiles are named after their south-west corner, e.g. N12 E075."""
    ns, ew = ("N" if lat0 >= 0 else "S"), ("E" if lon0 >= 0 else "W")
    return f"Copernicus_DSM_COG_30_{ns}{abs(lat0):02d}_00_{ew}{abs(lon0):03d}_00_DEM"


def tiles_for(cells: list[str]) -> set[tuple[int, int]]:
    need = set()
    for c in cells:
        lat, lon = (float(x) for x in c.split("_"))
        for la in (math.floor(lat - HALF), math.floor(lat + HALF - 1e-9)):
            for lo in (math.floor(lon - HALF), math.floor(lon + HALF - 1e-9)):
                need.add((la, lo))
    return need


def download(tiles: set[tuple[int, int]]) -> dict[tuple[int, int], Path]:
    DEM_DIR.mkdir(parents=True, exist_ok=True)
    have = {}
    todo = sorted(tiles)
    for i, (la, lo) in enumerate(todo, 1):
        name = tile_name(la, lo)
        path, sea = DEM_DIR / f"{name}.tif", DEM_DIR / f"{name}.sea"
        if path.exists():
            have[(la, lo)] = path
            continue
        if sea.exists():
            continue
        url = f"{BASE}/{name}/{name}.tif"
        r = requests.get(url, timeout=120, stream=True)
        if r.status_code in (403, 404):            # no tile = only sea there
            sea.touch()
            print(f"  [{i}/{len(todo)}] {name}: sea only, skipped")
            continue
        r.raise_for_status()
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(path)
        have[(la, lo)] = path
        print(f"  [{i}/{len(todo)}] {name}: {path.stat().st_size / 1e6:.1f} MB")
    return have


def read_square(datasets: list, lat: float, lon: float):
    """Elevation array covering the square (tiles stitched together) and its pixel size in degrees."""
    from rasterio.merge import merge
    arr, transform = merge(datasets, bounds=(lon - HALF, lat - HALF, lon + HALF, lat + HALF), nodata=np.nan)
    return arr[0].astype("float64"), abs(transform.a), abs(transform.e)


def stats(z: np.ndarray, res_x_deg: float, res_y_deg: float, lat: float) -> dict:
    """Slope at every pixel from its neighbours (central differences), then the summary numbers."""
    z = np.where(np.isfinite(z) & (z > 0), z, np.nan)          # sea, lakes, no data -> left out
    dy = res_y_deg * 111_320.0
    dx = res_x_deg * 111_320.0 * math.cos(math.radians(lat))
    gy, gx = np.gradient(z, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    land = np.isfinite(slope)
    if land.sum() < 50:
        return {"slope_p90": 0.0, "steep_share": 0.0, "relief": 0.0, "elev_mean": 0.0}
    s, e = slope[land], z[np.isfinite(z)]
    return {"slope_p90": round(float(np.percentile(s, 90)), 2),
            "steep_share": round(float((s > STEEP_DEG).mean()), 4),
            "relief": round(float(np.percentile(e, 99) - np.percentile(e, 1)), 1),
            "elev_mean": round(float(e.mean()), 1)}


def main() -> None:
    import rasterio

    with open(VILLAGES, newline="", encoding="utf-8") as f:
        cells = sorted({r["cell_id"] for r in csv.DictReader(f)})
    need = tiles_for(cells)
    print(f"{len(cells)} squares need {len(need)} elevation tiles (downloaded once, kept in {DEM_DIR.relative_to(ROOT)})")
    have = download(need)
    open_tiles = {k: rasterio.open(p) for k, p in have.items()}
    rows = []
    for i, c in enumerate(cells, 1):
        lat, lon = (float(x) for x in c.split("_"))
        ds = [open_tiles[k] for k in tiles_for([c]) if k in open_tiles]
        if not ds:
            rows.append({"cell_id": c, "slope_p90": 0.0, "steep_share": 0.0, "relief": 0.0, "elev_mean": 0.0})
            continue
        z, rx, ry = read_square(ds, lat, lon)
        rows.append({"cell_id": c, **stats(z, rx, ry, lat)})
        if i % 50 == 0 or i == len(cells):
            print(f"  {i}/{len(cells)} squares done")
    for d in open_tiles.values():
        d.close()
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    steep = sorted(rows, key=lambda r: -r["slope_p90"])[:5]
    flat = sorted(rows, key=lambda r: r["slope_p90"])[:3]
    print("steepest: " + ", ".join(f"{r['cell_id']} ({r['slope_p90']} deg, {r['steep_share']:.0%} steep)" for r in steep))
    print("flattest: " + ", ".join(f"{r['cell_id']} ({r['slope_p90']} deg)" for r in flat))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
