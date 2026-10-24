"""
Open-Meteo rainfall for every grid square, so build_grid.py can work out how far Open-Meteo is
from IMD's gauge data in each square and month (the "bias factors").

Downloads one wet season (June to November) of daily rain from Open-Meteo's free archive for each
of the ~310 squares, a few squares per request with pauses, to stay inside the free limit
(10,000 calls a day; a long date range counts as several calls). Takes roughly 10-20 minutes.
It can be stopped and re-run: squares already saved are skipped.

Input : ml/data/karnataka_villages.csv
Output: ml/data/raw/om_grid/<cell_id>.csv   (date, rain_mm)

Run from the project root, then re-run build_grid.py:
    python ml/scripts/fetch_grid_bias.py --year 2024
    python ml/scripts/build_grid.py
Use a year that your IMD files also have (build_grid compares the two day by day).
"""
import argparse
import csv
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
VILLAGES = ROOT / "ml" / "data" / "karnataka_villages.csv"
OUT_DIR = ROOT / "ml" / "data" / "raw" / "om_grid"
URL = "https://archive-api.open-meteo.com/v1/archive"
PER_REQUEST = 10
PAUSE_S = 20


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(VILLAGES, newline="", encoding="utf-8") as f:
        cells = sorted({r["cell_id"] for r in csv.DictReader(f)})
    todo = [c for c in cells if not (OUT_DIR / f"{c}.csv").exists()]
    print(f"{len(cells)} squares, {len(todo)} still to download")

    for i in range(0, len(todo), PER_REQUEST):
        batch = todo[i:i + PER_REQUEST]
        params = {"latitude": ",".join(c.split("_")[0] for c in batch),
                  "longitude": ",".join(c.split("_")[1] for c in batch),
                  "start_date": f"{args.year}-06-01", "end_date": f"{args.year}-11-30",
                  "daily": "precipitation_sum", "timezone": "Asia/Kolkata"}
        for attempt in range(1, 6):
            r = requests.get(URL, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 60 * attempt
                print(f"  busy or limit reached ({r.status_code}); waiting {wait} s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        else:
            raise SystemExit("Open-Meteo kept refusing. Wait an hour (or until tomorrow) and run again; it resumes.")
        results = r.json()
        results = results if isinstance(results, list) else [results]
        for c, res in zip(batch, results):
            with open(OUT_DIR / f"{c}.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "rain_mm"])
                for d, v in zip(res["daily"]["time"], res["daily"]["precipitation_sum"]):
                    w.writerow([d, "" if v is None else v])
        print(f"  {min(i + PER_REQUEST, len(todo))}/{len(todo)} squares saved")
        if i + PER_REQUEST < len(todo):
            time.sleep(PAUSE_S)
    print(f"done: files in {OUT_DIR.relative_to(ROOT)}. Now run: python ml/scripts/build_grid.py")


if __name__ == "__main__":
    main()
