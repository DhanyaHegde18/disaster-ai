"""
River flood check: GloFAS's discharge forecast at each river point compared with that point's own flood levels
(built by ml/scripts/build_rivers.py from 2005-2022 history).

  MEDIUM  the river is expected to reach the level it reaches about every 2nd year
  HIGH    ... about every 5th year

A river at MEDIUM or HIGH raises every rain-grid square holding villages within the point's radius, with a reason
naming the river. Unlike the landslide model, a river can raise a square to HIGH on its own: discharge is a
direct measure of the flood, and North Karnataka's river floods often come with little local rain.

Rivers are skipped (nothing changes) until backend/app/river_config.json exists.
"""
import json
import time
from datetime import date
from functools import lru_cache

import requests

from .. import config
from .risk_engine import LEVELS


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> dict:
    return json.loads(open(path, encoding="utf-8").read())


def live_points(cfg: dict) -> dict:
    """The points used for warnings (those that turned out to be small streams are left out)."""
    return {pid: p for pid, p in cfg["points"].items() if not p.get("small")}


def river_config() -> dict | None:
    if not config.RIVER_CONFIG.exists():
        return None
    return _load(str(config.RIVER_CONFIG), config.RIVER_CONFIG.stat().st_mtime)


def fetch_discharge(points: dict[str, tuple[float, float]]) -> dict[str, list[tuple[date, float]]]:
    """{id: (lat, lon)} -> {id: [(day, m3/s), ...]} from yesterday to RIVER_DAYS_AHEAD days ahead. One request."""
    ids = list(points)
    params = {"latitude": ",".join(str(points[k][0]) for k in ids),
              "longitude": ",".join(str(points[k][1]) for k in ids),
              "daily": "river_discharge", "past_days": 1, "forecast_days": config.RIVER_DAYS_AHEAD + 1}
    last = None
    for attempt in range(1, config.RETRIES + 1):
        try:
            r = requests.get(config.FLOOD_URL, params=params, timeout=config.REQUEST_TIMEOUT_S)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} server busy")
            r.raise_for_status()
            payload = r.json()
            payload = payload if isinstance(payload, list) else [payload]
            return {k: [(date.fromisoformat(d), float(q or 0.0))
                        for d, q in zip(res["daily"]["time"], res["daily"]["river_discharge"])]
                    for k, res in zip(ids, payload)}
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout, ValueError, KeyError) as err:
            last = err
            if attempt < config.RETRIES:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Open-Meteo flood API unavailable after {config.RETRIES} tries: {last}")


def assess(cfg: dict, daily: dict, today: date) -> list[dict]:
    """One result per river point: the highest discharge from today to RIVER_DAYS_AHEAD days ahead."""
    out = []
    for pid, p in cfg["points"].items():
        if p.get("small"):                       # a stream, not the river (see ml/reports/rivers.md): not used
            continue
        series = [(d, q) for d, q in daily.get(pid, []) if d >= today][:config.RIVER_DAYS_AHEAD + 1]
        if not series:
            continue
        peak_day, peak = max(series, key=lambda x: x[1])
        level = "HIGH" if peak >= p["high"] else "MEDIUM" if peak >= p["medium"] else "LOW"
        out.append({"point_id": pid, "river": p["river"], "river_kn": p.get("river_kn") or p["river"],
                    "place": p["place"], "lat": p["lat"], "lon": p["lon"], "level": level,
                    "peak_m3s": round(peak, 1), "peak_day": peak_day.isoformat(),
                    "medium_m3s": p["medium"], "high_m3s": p["high"], "record_m3s": p.get("record"),
                    "taluk_ids": p.get("taluk_ids", []), "cells": p.get("cells", []),
                    "villages": p.get("villages", 0), "radius_km": p.get("radius_km"),
                    "daily": [{"date": d.isoformat(), "m3s": round(q, 1)} for d, q in series]})
    out.sort(key=lambda r: (-LEVELS.index(r["level"]), -r["peak_m3s"] / max(r["high_m3s"], 1)))
    return out


def reason(r: dict) -> str:
    often = "about every 5th year" if r["level"] == "HIGH" else "about every 2nd year"
    return (f"{r['river']} river at {r['place']}: up to {r['peak_m3s']:,.0f} m³/s by {r['peak_day']} "
            f"(≥ {r[r['level'].lower() + '_m3s']:,.0f}, a flood reached {often})")


def add_rivers(cells: list[dict], rivers: list[dict]) -> list[dict]:
    """Raise the squares near rising rivers. Each square remembers which rivers touch it and whether its level
    now comes from a river (`level_cause`), so alerts can say so."""
    by_id = {c["cell_id"]: c for c in cells}
    for r in rivers:
        if r["level"] == "LOW":
            continue
        for cid in r["cells"]:
            c = by_id.get(cid)
            if not c:
                continue
            c.setdefault("rivers", []).append(r["point_id"])
            c["reasons"] = [x for x in c["reasons"] if x != "Rainfall below warning thresholds"] + [reason(r)]
            if LEVELS.index(r["level"]) > LEVELS.index(c["level"]):
                c["level"], c["level_cause"] = r["level"], "river"
    cells.sort(key=lambda r: (-LEVELS.index(r["level"]), -r["forecast_3d_mm"]))
    return cells
