"""
Flood levels for Karnataka's big rivers, so the system can warn about river floods that local rain can't
explain (North Karnataka's Krishna and Bhima floods come from rain far upstream and from dam releases).

Source : GloFAS v4 (Copernicus Global Flood Awareness System) river discharge, ~5 km grid, through Open-Meteo's
         free flood API (no key): https://flood-api.open-meteo.com. The API returns the largest river within
         about 5 km of a point, so the points in ml/data/river_points.csv only need to be near the river.
Method : for each point, daily discharge (m3/s) for every June-November from 2005 to 2022 (GloFAS's consolidated
         reanalysis; includes the 2005, 2009, 2018 and 2019 floods). From each year's highest day:
           MEDIUM = the level reached in about every 2nd year   (median of the yearly peaks)
           HIGH   = the level reached in about every 5th year   (80th percentile of the yearly peaks)
         The live check later compares GloFAS's own forecast with these, so forecast and thresholds come from
         the same model (no bias correction needed, unlike rain).
         Villages within each point's radius_km are the ones it warns; their taluks and rain-grid squares are saved.
Output : backend/app/river_config.json and ml/reports/rivers.md

First each point is moved onto the main river within about 11 km (snap(): a town's GloFAS cell is sometimes a
small stream beside the river). Open-Meteo counts a long request as several calls (about one per 2 weeks per
location): finding the rivers costs about 2,000 calls, the history about 6,500 (only points that moved are fetched
again), with at most 5,000 an hour, so it pauses when told to. Everything is saved in ml/data/raw/glofas/ as it
arrives, so it is safe to stop and re-run.

Run from the project root:
    python ml/scripts/build_rivers.py
"""
import csv
import json
import math
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import areas, config  # noqa: E402

POINTS_CSV = ROOT / "ml" / "data" / "river_points.csv"
CACHE = ROOT / "ml" / "data" / "raw" / "glofas"
OUT = ROOT / "backend" / "app" / "river_config.json"
REPORT = ROOT / "ml" / "reports" / "rivers.md"
YEARS = range(2005, 2023)              # GloFAS v4 reanalysis ends in July 2022; 2022's monsoon comes from the forecast archive
SEASON = ("06-01", "11-30")
KNOWN_FLOOD_YEARS = (2009, 2018, 2019)
SMALL_M3S = 300                         # a record flood below this is a stream, not one of the big rivers  # Oct 2009 North Karnataka, Aug 2018 Kodagu / coast, Aug 2019 Krishna basin and Malnad


def read_points(path: Path = POINTS_CSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{**r, "lat": float(r["lat"]), "lon": float(r["lon"]), "radius_km": float(r.get("radius_km") or 10)}
                for r in csv.DictReader(f)]


def _get(params: dict, label: str) -> list:
    """One Open-Meteo flood API request, waiting when it says too many calls this hour."""
    for attempt in range(1, 7):
        try:
            r = requests.get(config.FLOOD_URL, params=params, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as err:
            print(f"  {label}: {type(err).__name__}; retrying in 30 s")
            time.sleep(30)
            continue
        if r.status_code == 429:
            print(f"  {label}: Open-Meteo says too many calls this hour ({r.text[:80]}); waiting 15 min")
            time.sleep(15 * 60)
            continue
        r.raise_for_status()
        payload = r.json()
        return payload if isinstance(payload, list) else [payload]
    raise SystemExit(f"Open-Meteo kept refusing ({label}). Run again later; finished parts are kept.")


def _same_place(entry, p: dict) -> bool:
    """A cached series belongs to a point only if it was fetched at the point's current position.
    (Old caches stored plain lists, fetched at the position written in river_points.csv.)"""
    if isinstance(entry, list):
        return (p["lat"], p["lon"]) == (p.get("csv_lat", p["lat"]), p.get("csv_lon", p["lon"]))
    return abs(entry["lat"] - p["lat"]) < 1e-6 and abs(entry["lon"] - p["lon"]) < 1e-6


def fetch_year(points: list[dict], year: int) -> dict[str, list[float]]:
    """{point_id: [daily discharge over June-November]} for one year. Only points not cached at their
    current position are downloaded."""
    path = CACHE / f"{year}.json"
    cached = json.loads(path.read_text()) if path.exists() else {}
    todo = [p for p in points if p["point_id"] not in cached or not _same_place(cached[p["point_id"]], p)]
    if todo:
        params = {"latitude": ",".join(str(p["lat"]) for p in todo),
                  "longitude": ",".join(str(p["lon"]) for p in todo),
                  "daily": "river_discharge", "start_date": f"{year}-{SEASON[0]}", "end_date": f"{year}-{SEASON[1]}"}
        for p, res in zip(todo, _get(params, str(year))):
            cached[p["point_id"]] = {"lat": p["lat"], "lon": p["lon"],
                                     "q": [float(x) for x in res["daily"]["river_discharge"] if x is not None]}
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cached))
    return {p["point_id"]: (cached[p["point_id"]] if isinstance(cached[p["point_id"]], list)
                            else cached[p["point_id"]]["q"]) for p in points}


SNAP_STEP = 0.05            # GloFAS cells are 0.05 degrees
SNAP_RINGS = 2              # look up to 2 cells (about 11 km) away in each direction
SNAP_MONTH = ("2020-08-01", "2020-08-31")    # an ordinary monsoon month: the main river always carries the most
SNAP_FILE = CACHE / "snap.json"


SNAP_SHARE = 0.8            # a cell with at least 80% of the biggest flow nearby is "on the main river"


def choose(origin: tuple[float, float], cands: list[tuple[float, float]], means: list[float]) -> int:
    """Index of the cell to use: among cells carrying at least SNAP_SHARE of the biggest nearby flow (the main
    river), the one closest to the town. Rivers carry more water downstream, so "most water" alone would drag every
    point 10-15 km downstream, away from the villages it should warn."""
    top = max(means)
    on_river = [i for i, m in enumerate(means) if m >= SNAP_SHARE * top and m > 0]
    return min(on_river, key=lambda i: km(origin[0], origin[1], *cands[i]))


def snap(points: list[dict]) -> dict[str, dict]:
    """Move each point onto the main river near it. GloFAS's 5 km cells don't always put the river where the
    town is, and a point next to the Krishna can land on a small stream (flood level 3 m3/s instead of 5,000).
    The 25 cells within about 11 km are compared on their August 2020 average discharge (an ordinary monsoon
    month), and choose() picks one. The flows of all 25 cells are cached, so changing the rule costs no calls.
    {point_id: {"lat", "lon", "mean", "mean_before", "moved_km"}}"""
    done = json.loads(SNAP_FILE.read_text()) if SNAP_FILE.exists() else {}
    offs = [(dy * SNAP_STEP, dx * SNAP_STEP) for dy in range(-SNAP_RINGS, SNAP_RINGS + 1)
            for dx in range(-SNAP_RINGS, SNAP_RINGS + 1)]
    for p in points:
        key = f"{p['lat']:.4f},{p['lon']:.4f}"
        cands = [(round(p["lat"] + dy, 4), round(p["lon"] + dx, 4)) for dy, dx in offs]
        entry = done.get(p["point_id"], {})
        if entry.get("from") == key and "means" in entry:
            means = entry["means"]
        else:
            params = {"latitude": ",".join(str(c[0]) for c in cands), "longitude": ",".join(str(c[1]) for c in cands),
                      "daily": "river_discharge", "start_date": SNAP_MONTH[0], "end_date": SNAP_MONTH[1]}
            means = [round(float(np.mean([x for x in res["daily"]["river_discharge"] if x is not None] or [0.0])), 1)
                     for res in _get(params, f"snap {p['point_id']}")]
            time.sleep(1)
        here = means[cands.index((round(p["lat"], 4), round(p["lon"], 4)))]
        best = choose((p["lat"], p["lon"]), cands, means)
        lat, lon = cands[best]
        done[p["point_id"]] = {"from": key, "means": means, "lat": lat, "lon": lon, "mean": means[best],
                               "mean_before": here, "moved_km": round(km(p["lat"], p["lon"], lat, lon), 1)}
        SNAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        SNAP_FILE.write_text(json.dumps(done, indent=1))
        m = done[p["point_id"]]
        print(f"  {p['point_id']:<26} " + (f"moved {m['moved_km']} km: August flow {here:,.0f} -> {m['mean']:,.0f} m3/s"
                                          if m["moved_km"] else f"already on the main river ({here:,.0f} m3/s)"))
    return done


def flood_levels(peaks_by_year: dict[int, float]) -> dict:
    """2-year and 5-year flood levels from each year's peak, plus the biggest years."""
    peaks = np.array(list(peaks_by_year.values()), dtype=float)
    top = sorted(peaks_by_year, key=lambda y: -peaks_by_year[y])[:3]
    return {"medium": round(float(np.percentile(peaks, 50)), 1), "high": round(float(np.percentile(peaks, 80)), 1),
            "record": round(float(peaks.max()), 1), "top_years": top, "years": len(peaks)}


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    return math.hypot(a_lat - b_lat, (a_lon - b_lon) * math.cos(math.radians(a_lat))) * 111.32


def affected(a, p: dict) -> dict:
    """Villages within the point's radius: how many, and which taluks and rain-grid squares they are in."""
    near = [v for v in a.villages.values() if km(p["lat"], p["lon"], v["lat"], v["lon"]) <= p["radius_km"]]
    return {"villages": len(near), "taluk_ids": sorted({v["taluk_id"] for v in near}),
            "cells": sorted({v["cell_id"] for v in near}),
            "places": [v["name"] for v in sorted(near, key=lambda v: -v["population"])[:3]]}


def write_report(cfg: dict) -> None:
    pts = cfg["points"]
    hit = [pid for pid, p in pts.items() if set(p["top_years"]) & set(KNOWN_FLOOD_YEARS)]
    small = [pid for pid, p in pts.items() if p["record"] < SMALL_M3S]
    lines = [
        "# River flood levels (GloFAS v4 via Open-Meteo)", "",
        f"Built {cfg['created']} from June-November discharge, {cfg['years'][0]}-{cfg['years'][-1]} "
        f"({len(cfg['years'])} yearly peaks per point). MEDIUM = level reached about every 2nd year, "
        "HIGH = about every 5th year.", "",
        "**Sanity check:** the three biggest years at each point should include a year Karnataka remembers for river "
        f"floods ({', '.join(map(str, KNOWN_FLOOD_YEARS))}). That holds at **{len(hit)} of {len(pts)} points**. "
        "A small stream beside a big river floods in the same years, so this check alone is weak.", "",
        f"**Size check:** a big river's record flood is hundreds to thousands of m³/s. **{len(small)} of {len(pts)} points** "
        f"stay below {SMALL_M3S} m³/s (⚠ small) even after moving each point onto the biggest river within about 11 km: "
        "they are left out of live warnings. Check them on the map or remove them from ml/data/river_points.csv "
        "(dam-controlled rivers like the Kali and Sharavathi can look small in GloFAS).", "",
        "| Point | MEDIUM m³/s | HIGH m³/s | Record m³/s | Biggest years | Moved | Villages warned |",
        "|---|---|---|---|---|---|---|",
    ]
    for pid, p in pts.items():
        mark = "" if pid in hit else " ⚠"
        size = " ⚠ small" if pid in small else ""
        moved = f"{p.get('moved_km', 0):g} km" if p.get("moved_km") else "–"
        lines.append(f"| {p['river']} at {p['place']} | {p['medium']:,.0f} | {p['high']:,.0f} | {p['record']:,.0f}{size} | "
                     f"{', '.join(map(str, p['top_years']))}{mark} | {moved} | {p['villages']} |")
    lines += ["", "Limits: GloFAS is a model, not a gauge. It represents big dams in a simplified way, while real "
              "releases from Almatti, Narayanpur, Tungabhadra or Kabini are decided by people, so warnings are a "
              "guide to check with the river and dam authorities (CWC, KNNL), not a measurement.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="River flood levels from GloFAS")
    ap.add_argument("--no-snap", action="store_true", help="use the positions in river_points.csv exactly")
    args = ap.parse_args()
    points = read_points()
    for p in points:
        p["csv_lat"], p["csv_lon"], p["moved_km"] = p["lat"], p["lon"], 0.0
    if not args.no_snap:
        print(f"finding the biggest river near each of {len(points)} points (about 75 Open-Meteo calls each, cached) ...")
        snapped = snap(points)
        for p in points:
            sp = snapped[p["point_id"]]
            p["lat"], p["lon"], p["moved_km"] = sp["lat"], sp["lon"], sp["moved_km"]
    print(f"{len(points)} river points, June-November {YEARS[0]}-{YEARS[-1]} (cached years are reused)")
    series = {p["point_id"]: {} for p in points}
    for year in YEARS:
        got = fetch_year(points, year)
        for pid, vals in got.items():
            if vals and pid in series:
                series[pid][year] = max(vals)
        print(f"  {year} done")
        time.sleep(2)
    a = areas.get()
    cfg = {"created": date.today().isoformat(), "source": "GloFAS v4 river discharge via Open-Meteo flood API",
           "years": list(YEARS), "points": {}}
    for p in points:
        peaks = series[p["point_id"]]
        if len(peaks) < 10 or max(peaks.values()) <= 0:
            print(f"  {p['point_id']}: no river found there (all zero or missing); move the point closer to the river")
            continue
        cfg["points"][p["point_id"]] = {"river": p["river"], "river_kn": p["river_kn"], "place": p["place"],
                                        "lat": p["lat"], "lon": p["lon"], "radius_km": p["radius_km"],
                                        "moved_km": p["moved_km"],
                                        **flood_levels(peaks), **affected(a, p)}
        cfg["points"][p["point_id"]]["small"] = cfg["points"][p["point_id"]]["record"] < SMALL_M3S   # not used live
    OUT.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(cfg)
    for pid, p in cfg["points"].items():
        print(f"  {p['river']:<12} {p['place']:<15} MEDIUM {p['medium']:>8,.0f}  HIGH {p['high']:>8,.0f} m3/s   "
              f"biggest years {p['top_years']}   {p['villages']} villages")
    small = [pid for pid, p in cfg["points"].items() if p["small"]]
    if small:
        print(f"left out of live warnings (record flood below {SMALL_M3S} m3/s, probably not the main river): {', '.join(small)}")
    print(f"saved {OUT.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
