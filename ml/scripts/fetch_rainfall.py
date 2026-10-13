"""
Phase 1, step 1: download daily rainfall history for every village.

Source: Open-Meteo historical weather API (free, no API key, non-commercial use).
Input : ml/data/villages.csv   (village_id, name, district, lat, lon)
Output: ml/data/raw/rainfall/<village_id>.csv   (village_id, date, rain_mm)

Run from the project root:
    python ml/scripts/fetch_rainfall.py --start 2015-01-01 --end 2025-12-31

Already-downloaded villages are skipped, so you can re-run it safely
after adding new villages or if it stops halfway.
"""
import argparse
import time
from pathlib import Path

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ML_DIR = Path(__file__).resolve().parents[1]
VILLAGES_CSV = ML_DIR / "data" / "villages.csv"
OUT_DIR = ML_DIR / "data" / "raw" / "rainfall"


def fetch_village(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    """Return one row per day with total rainfall in mm for a single point."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "precipitation_sum",
        "timezone": "Asia/Kolkata",
    }
    # The free server sometimes returns 502/504 when busy, so retry with a growing wait.
    for attempt in range(1, 5):
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code} server busy")
            resp.raise_for_status()
            break
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as err:
            if attempt == 4:
                raise
            wait = 5 * attempt
            print(f"  retry {attempt}/3 in {wait}s ({err})")
            time.sleep(wait)
    daily = resp.json()["daily"]
    return pd.DataFrame(
        {"date": pd.to_datetime(daily["time"]), "rain_mm": daily["precipitation_sum"]}
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--start", default="2015-01-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default="2025-12-31", help="YYYY-MM-DD")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="seconds to wait between requests (be polite to the free API)")
    args = parser.parse_args()

    villages = pd.read_csv(VILLAGES_CSV)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for v in villages.itertuples(index=False):
        out_file = OUT_DIR / f"{v.village_id}.csv"
        if out_file.exists():
            print(f"skip   {v.village_id} ({v.name}) - already downloaded")
            continue
        try:
            df = fetch_village(v.lat, v.lon, args.start, args.end)
        except (requests.RequestException, KeyError) as err:
            print(f"FAILED {v.village_id} ({v.name}): {err}")
            continue
        df.insert(0, "village_id", v.village_id)
        df.to_csv(out_file, index=False)
        missing = df["rain_mm"].isna().sum()
        print(f"saved  {v.village_id} ({v.name}): {len(df)} days, {missing} missing")
        time.sleep(args.pause)


if __name__ == "__main__":
    main()