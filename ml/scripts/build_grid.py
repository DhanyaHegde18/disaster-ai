"""
Calibrate the state-wide warning rule on IMD's 0.25 degree rain grid (about 27 km squares).

Why a grid: one set of thresholds can't fit Agumbe (8 m of rain a year) and Kolar (under 1 m).
Each grid square gets its own thresholds from its own rain history; each village takes the
level of the square it lies in (cell_id in ml/data/karnataka_villages.csv).

Per square, over wet-season days (June to November: south-west AND north-east monsoon):
  past_3d      rain over the last 3 days (today included)
  forecast_3d  rain over the next 3 days
  MEDIUM = wettest 15% of wet-season days, but at least 64.5 mm   (IMD "heavy rain" in one day)
  HIGH   = wettest 5%  of wet-season days, but at least 115.6 mm  (IMD "very heavy rain" in one day)
The floors stop dry districts from getting a HIGH every year for ordinary rain.

Open-Meteo bias: the live forecast comes from Open-Meteo, which under-counts Western Ghats
downpours badly. If you ran fetch_grid_bias.py, each square also gets monthly factors
(IMD total / Open-Meteo total, limited to 0.5-3.0) so live values are scaled to IMD's level.

Input : ml/data/raw/imd_grd/rain/<year>.grd   (already downloaded by fetch_rainfall_imd.py)
        ml/data/karnataka_villages.csv           (which squares have villages)
        ml/data/raw/om_grid/<cell>.csv           (optional, from fetch_grid_bias.py)
        ml/data/villages.csv + events.csv        (the 11 past events, for the replay check)
Output: backend/app/grid_config.json

Run from the project root:
    python ml/scripts/build_grid.py                     # uses every year found in imd_grd
    python ml/scripts/build_grid.py --start-year 2015 --end-year 2025
    python ml/scripts/build_grid.py --demo              # placeholder thresholds, no IMD data needed
                                                        # (writes grid_config.demo.json; the app says DEMO)
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml" / "data"
GRD_DIR = DATA / "raw" / "imd_grd"
OM_DIR = DATA / "raw" / "om_grid"
VILLAGES = DATA / "karnataka_villages.csv"
OUT = ROOT / "backend" / "app" / "grid_config.json"
DEMO_OUT = ROOT / "backend" / "app" / "grid_config.demo.json"

WET_MONTHS = (6, 7, 8, 9, 10, 11)
FLOOR = {"medium": 64.5, "high": 115.6}
BIAS_MIN, BIAS_MAX, BIAS_MIN_OM_MM = 0.5, 3.0, 20.0
KA_BOX = {"lat": (11.25, 18.75), "lon": (73.75, 78.75)}   # Karnataka plus one square of margin
LEVELS = ["LOW", "MEDIUM", "HIGH"]


def cell_id(lat: float, lon: float) -> str:
    return f"{lat:.2f}_{lon:.2f}"


def needed_cells() -> dict[str, int]:
    with open(VILLAGES, newline="", encoding="utf-8") as f:
        return Counter(r["cell_id"] for r in csv.DictReader(f))


def available_years() -> list[int]:
    folder = GRD_DIR / "rain" if (GRD_DIR / "rain").exists() else GRD_DIR
    return sorted(int(m.group(1)) for p in folder.glob("*.grd") if (m := re.fullmatch(r"(\d{4})\.grd", p.name)))


def load_imd(years: list[int], cells: set[str]) -> pd.DataFrame:
    """Daily rain (mm) as a table: one row per day, one column per grid square. Read a year at a time
    and cut to Karnataka straight away, so the whole-India files don't fill the laptop's memory."""
    import imdlib as imd    # only needed here, so the tests can run without it

    parts = []
    for y in years:
        ds = imd.open_data("rain", y, y, "yearwise", str(GRD_DIR)).get_xarray()
        da = ds["rain"].sel(lat=slice(*KA_BOX["lat"]), lon=slice(*KA_BOX["lon"]))
        frame = da.stack(cell=("lat", "lon")).to_pandas()
        frame.columns = [cell_id(lat, lon) for lat, lon in frame.columns]
        parts.append(frame[[c for c in frame.columns if c in cells]])
        print(f"  {y}: {len(frame)} days")
    daily = pd.concat(parts).sort_index()
    daily.index = pd.to_datetime(daily.index)
    return daily.where(daily > -900)          # -999 = no data


def thresholds(series: pd.Series) -> dict:
    wet = series[series.index.month.isin(WET_MONTHS)].dropna()
    if len(wet) < 60:
        return {"medium": FLOOR["medium"], "high": FLOOR["high"], "note": "too little data: floors used"}
    return {"medium": round(max(float(wet.quantile(0.85)), FLOOR["medium"]), 1),
            "high": round(max(float(wet.quantile(0.95)), FLOOR["high"]), 1)}


def level_for(v: float, t: dict) -> int:
    return 2 if v >= t["high"] else 1 if v >= t["medium"] else 0


def bias_factors(cell: str, imd_daily: pd.Series) -> dict:
    """Monthly IMD / Open-Meteo factors from days both have. Empty if no Open-Meteo file."""
    f = OM_DIR / f"{cell}.csv"
    if not f.exists():
        return {}
    om = pd.read_csv(f, parse_dates=["date"]).set_index("date")["rain_mm"]
    both = pd.concat([imd_daily.rename("imd"), om.rename("om")], axis=1).dropna()
    out = {}
    for month, g in both.groupby(both.index.month):
        if g["om"].sum() >= BIAS_MIN_OM_MM:
            out[str(month)] = round(float(np.clip(g["imd"].sum() / g["om"].sum(), BIAS_MIN, BIAS_MAX)), 2)
    return out


def calibrate(daily: pd.DataFrame, cells: dict[str, int]) -> tuple[dict, dict]:
    """Thresholds per square, plus 3-day sums kept for the replay."""
    out, sums = {}, {}
    for c in cells:
        if c not in daily.columns:
            continue
        s = daily[c]
        past = s.rolling(3, min_periods=3).sum()
        nxt = past.shift(-3)                       # day +1..+3
        lat, lon = (float(x) for x in c.split("_"))
        out[c] = {"lat": lat, "lon": lon, "villages": cells[c],
                  "past_3d": thresholds(past), "forecast_3d": thresholds(nxt), "bias": bias_factors(c, s)}
        sums[c] = (past, nxt)
    return out, sums


def replay(sums: dict, grid: dict) -> list[dict]:
    """Highest level the rule reached in the 3 days before each past event."""
    ev_file, v_file = DATA / "events.csv", DATA / "villages.csv"
    if not (ev_file.exists() and v_file.exists()):
        return []
    villages = pd.read_csv(v_file).set_index("village_id")
    rows = []
    for e in pd.read_csv(ev_file, parse_dates=["date"]).itertuples(index=False):
        v = villages.loc[e.village_id]
        c = cell_id(6.5 + round((v.lat - 6.5) / 0.25) * 0.25, 66.5 + round((v.lon - 66.5) / 0.25) * 0.25)
        best = "NO DATA"
        if c in sums:
            past, nxt = sums[c]
            window = (past.index < e.date) & (past.index >= e.date - pd.Timedelta(days=3))
            lv = [max(level_for(p, grid[c]["past_3d"]), level_for(n, grid[c]["forecast_3d"]))
                  for p, n in zip(past[window], nxt[window]) if not (np.isnan(p) or np.isnan(n))]
            if lv:
                best = LEVELS[max(lv)]
        rows.append({"place": v["name"], "cell_id": c, "date": str(e.date.date()), "type": e.event_type,
                     "level_before": best})
    return rows


def alert_load(sums: dict, grid: dict) -> dict:
    high = medium = seasons = 0
    for c, (past, nxt) in sums.items():
        wet = past.index.month.isin(WET_MONTHS)
        lv = np.maximum([level_for(p, grid[c]["past_3d"]) if not np.isnan(p) else 0 for p in past[wet]],
                        [level_for(n, grid[c]["forecast_3d"]) if not np.isnan(n) else 0 for n in nxt[wet]])
        high += int((lv == 2).sum())
        medium += int((lv >= 1).sum())
        seasons += past.index[wet].year.nunique()
    seasons = max(seasons, 1)
    return {"high_days_per_square_per_season": round(high / seasons, 1),
            "medium_or_high_days_per_square_per_season": round(medium / seasons, 1)}


def write_demo() -> None:
    """Rough placeholder thresholds by longitude (coast and ghats wetter, plains drier), so the app runs
    before the real calibration. Never use these for real warnings."""
    cells = needed_cells()
    grid = {}
    for c, n in cells.items():
        lat, lon = (float(x) for x in c.split("_"))
        t = ({"medium": 137.0, "high": 198.0} if lon <= 75.5 else
             {"medium": 100.0, "high": 150.0} if lon <= 76.25 else dict(FLOOR))
        grid[c] = {"lat": lat, "lon": lon, "villages": n, "past_3d": dict(t), "forecast_3d": dict(t), "bias": {}}
    DEMO_OUT.write_text(json.dumps({"demo": True, "calibrated_on": None, "source": "placeholder (no IMD data)",
                                    "rule": "DEMO thresholds by longitude", "wet_season_months": list(WET_MONTHS),
                                    "floors_mm": FLOOR, "cells": grid, "event_replay": []}, indent=1))
    print(f"saved {DEMO_OUT} ({len(grid)} squares, placeholder thresholds)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int)
    ap.add_argument("--end-year", type=int)
    ap.add_argument("--demo", action="store_true", help="write placeholder thresholds instead (no IMD data needed)")
    args = ap.parse_args()
    if args.demo:
        write_demo()
        return

    years = [y for y in available_years()
             if (args.start_year is None or y >= args.start_year) and (args.end_year is None or y <= args.end_year)]
    if not years:
        raise SystemExit(f"No IMD year files in {GRD_DIR}. Run fetch_rainfall_imd.py first (it caches them there).")
    cells = needed_cells()
    print(f"IMD years {years[0]}-{years[-1]}, {len(cells)} grid squares with villages")
    daily = load_imd(years, set(cells))
    grid, sums = calibrate(daily, cells)
    missing = sorted(set(cells) - set(grid))
    with_bias = sum(bool(g["bias"]) for g in grid.values())

    cfg = {
        "calibrated_on": str(date.today()),
        "source": f"IMD 0.25 degree gridded rainfall {years[0]}-{years[-1]}",
        "rule": "level = higher of (past 3-day rain level, forecast 3-day rain level), per grid square",
        "wet_season_months": list(WET_MONTHS),
        "floors_mm": FLOOR,
        "rates": {"medium_or_high": 0.15, "high": 0.05},
        "historical_alert_load": alert_load(sums, grid),
        "cells": grid,
        "missing_cells": missing,
        "event_replay": replay(sums, grid),
    }
    OUT.write_text(json.dumps(cfg, indent=1))

    print(f"\n{len(grid)} squares calibrated, {with_bias} with Open-Meteo bias factors"
          + ("" if with_bias else "  <- run fetch_grid_bias.py, or Ghats forecasts will read too low"))
    if missing:
        print(f"no IMD data for {len(missing)} squares (on the coast edge?): {', '.join(missing[:8])}")
    print(f"alert load: {cfg['historical_alert_load']}")
    print("\nReplay: highest level in the 3 days before each past event")
    for r in cfg["event_replay"]:
        print(f"  {r['place']:<12} {r['date']} {r['type']:<9} {r['level_before']}")
    print(f"\nsaved {OUT}")


if __name__ == "__main__":
    main()
