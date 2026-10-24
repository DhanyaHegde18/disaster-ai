"""
Turn the state-wide snapshot (one result per rain-grid square) into what people need:
  taluk_risk()   one taluk's level, its worst square, and the villages most at risk (alerts use this)
  scoped_view()  what a staff member sees: their taluk / district / the whole state
"""
from .. import areas
from .risk_engine import LEVELS

PLACES_IN_ALERT = 4     # biggest villages named in an alert, so people recognise the area


def _by_id(snapshot: dict) -> dict:
    return {c["cell_id"]: c for c in snapshot["cells"]}


def taluk_risk(snapshot: dict, taluk_id: str, cells: dict | None = None) -> dict | None:
    a = areas.get()
    t = a.taluk(taluk_id)
    if not t:
        return None
    cells = cells or _by_id(snapshot)
    mine = [cells[c] for c in a.cells_by_taluk.get(taluk_id, ()) if c in cells]
    if not mine:
        return None
    worst = max(mine, key=lambda c: (LEVELS.index(c["level"]), c["forecast_3d_mm"], c["past_3d_mm"]))
    at_risk_cells = {c["cell_id"] for c in mine if c["level"] != "LOW"}
    worst_cells = {c["cell_id"] for c in mine if c["level"] == worst["level"]}
    villages = a.by_taluk.get(taluk_id, [])
    at_risk = [v for v in villages if v["cell_id"] in at_risk_cells]
    places = sorted((v for v in villages if v["cell_id"] in worst_cells), key=lambda v: -v["population"])
    return {
        "taluk_id": taluk_id, "name": t["name"], "district": t["district"], "district_kn": t.get("district_kn"),
        "level": worst["level"], "past_3d_mm": worst["past_3d_mm"], "forecast_3d_mm": worst["forecast_3d_mm"],
        "reasons": worst["reasons"], "daily_mm": worst["daily_mm"], "worst_cell": worst["cell_id"],
        "cells_at_risk": sorted(at_risk_cells),
        "villages_total": len(villages), "villages_at_risk": len(at_risk),
        "places": [v["name"] for v in places[:PLACES_IN_ALERT]],
    }


def all_taluk_risks(snapshot: dict, taluk_ids=None) -> list[dict]:
    a = areas.get()
    cells = _by_id(snapshot)
    out = [r for tid in (taluk_ids if taluk_ids is not None else a.taluks)
           if (r := taluk_risk(snapshot, tid, cells))]
    out.sort(key=lambda r: (-LEVELS.index(r["level"]), -r["forecast_3d_mm"], r["name"]))
    return out


def scoped_view(snapshot: dict, taluk_ids: set[str] | None, area_label: str) -> dict:
    """Risk for the taluks a staff member covers (None = whole state)."""
    a = areas.get()
    cells = _by_id(snapshot)
    tids = sorted(taluk_ids) if taluk_ids is not None else list(a.taluks)
    cell_ids = set().union(*(a.cells_by_taluk.get(t, set()) for t in tids)) if tids else set()
    taluks = all_taluk_risks(snapshot, tids)

    in_scope = set(tids)
    villages_by_level = {lv: 0 for lv in LEVELS[::-1]}
    shown_cells = []
    for cid in cell_ids:
        c = cells.get(cid)
        if not c:
            continue
        vs = [v for v in a.by_cell.get(cid, []) if v["taluk_id"] in in_scope]
        villages_by_level[c["level"]] += len(vs)
        biggest = sorted(vs, key=lambda v: -v["population"])[:3]
        shown_cells.append({**c, "villages": len(vs), "places": [v["name"] for v in biggest]})
    shown_cells.sort(key=lambda c: (-LEVELS.index(c["level"]), -c["forecast_3d_mm"]))

    view = {
        "generated_at": snapshot["generated_at"], "stale": snapshot.get("stale", False),
        "stale_reason": snapshot.get("stale_reason"), "demo_thresholds": snapshot.get("demo_thresholds", False),
        "calibrated_on": snapshot.get("calibrated_on"), "area": area_label,
        "summary": villages_by_level,                  # villages per level, in this area
        "squares": {lv: sum(c["level"] == lv for c in shown_cells) for lv in LEVELS[::-1]},
        "taluks": taluks, "cells": shown_cells,
    }
    if taluk_ids is not None and len(tids) == 1:      # one taluk: list its villages too
        level_of = {cid: cells[cid]["level"] for cid in cell_ids if cid in cells}
        vs = [{"village_id": v["village_id"], "name": v["name"], "cell_id": v["cell_id"], "lat": v["lat"],
               "lon": v["lon"], "population": v["population"], "level": level_of.get(v["cell_id"], "LOW")}
              for v in a.by_taluk.get(tids[0], [])]
        vs.sort(key=lambda v: (-LEVELS.index(v["level"]), v["name"]))
        view["villages"] = vs
    return view
