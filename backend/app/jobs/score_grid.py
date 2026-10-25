"""
Score every rain-grid square in Karnataka now and save the result to backend/data/latest_risk.json.

The API calls the same function when its cache is old, and the scheduler runs it every few hours.

Run from the project root:
    python -m backend.app.jobs.score_grid
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import areas, config
from ..services import landslide, rivers
from ..services.forecast import fetch_daily_rain
from ..services.risk_engine import assess_all, scaled_split


def score_now() -> dict:
    grid = config.grid_config()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    loaded = landslide.model()
    past_days = landslide.PAST_DAYS_NEEDED if loaded else 2
    daily = fetch_daily_rain({cid: (c["lat"], c["lon"]) for cid, c in grid["cells"].items()}, past_days=past_days)
    ls = {}
    if loaded:                                   # landslide chance per square from slope + rain
        rows = {cid: landslide.rain_features(*scaled_split(grid["cells"][cid], d, now.date()))
                for cid, d in daily.items() if cid in grid["cells"]}
        ls = landslide.predict_cells(rows)
    alone = config.LANDSLIDE_MODEL_ALONE_MAX if config.LANDSLIDE_MODEL_ALONE_MAX in ("MEDIUM", "HIGH") else "MEDIUM"
    cells = assess_all(daily, now.date(), grid, ls, loaded[1]["budgets"] if loaded else None, alone)
    river_cfg, river_results, river_error = rivers.river_config(), [], None
    if river_cfg:                                # river floods (GloFAS forecast vs each point's flood levels)
        try:
            q = rivers.fetch_discharge({pid: (p["lat"], p["lon"]) for pid, p in rivers.live_points(river_cfg).items()})
            river_results = rivers.assess(river_cfg, q, now.date())
            cells = rivers.add_rivers(cells, river_results)
        except RuntimeError as err:              # rain warnings still go out if the river service is down
            river_error = str(err)
    a = areas.get()
    villages = {lv: 0 for lv in ("HIGH", "MEDIUM", "LOW")}
    for c in cells:
        villages[c["level"]] += len(a.by_cell.get(c["cell_id"], []))
    snapshot = {
        "generated_at": now.isoformat(timespec="seconds"),
        "engine": "rule-v2-grid" + (f" + landslide {loaded[1]['model']}" if loaded else "")
                  + (" + rivers" if river_results else ""),
        "landslide_model": ({k: loaded[1][k] for k in ("model", "created", "years")} if loaded else None),
        "calibrated_on": grid.get("calibrated_on"),
        "demo_thresholds": grid.get("demo", False),
        "summary": {lv: sum(c["level"] == lv for c in cells) for lv in ("HIGH", "MEDIUM", "LOW")},
        "villages_by_level": villages,
        "cells": cells,
        "rivers": river_results,
        "rivers_error": river_error,
    }
    config.LATEST_RISK_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.LATEST_RISK_FILE.write_text(json.dumps(snapshot, ensure_ascii=False))
    return snapshot


if __name__ == "__main__":
    s = score_now()
    v = s["villages_by_level"]
    print(f"generated {s['generated_at']}   squares HIGH {s['summary']['HIGH']}  MEDIUM {s['summary']['MEDIUM']}  "
          f"LOW {s['summary']['LOW']}   villages HIGH {v['HIGH']}  MEDIUM {v['MEDIUM']}")
    for r in s["rivers"]:
        if r["level"] != "LOW":
            print(f"  river {r['river']} at {r['place']}: {r['level']} (up to {r['peak_m3s']:,.0f} m3/s by {r['peak_day']})")
    if s["rivers_error"]:
        print(f"  rivers skipped: {s['rivers_error']}")
    for c in s["cells"][:15]:
        if c["level"] != "LOW":
            print(f"  {c['cell_id']:<12} {c['level']:<6} past 3d {c['past_3d_mm']:>6} mm   next 3d {c['forecast_3d_mm']:>6} mm")
    print(f"saved {config.LATEST_RISK_FILE}")

    from .. import database
    from ..services.alerts import generate_for_snapshot
    database.init_db()
    created = generate_for_snapshot(s)
    print(f"alerts drafted: {len(created)}")
    for al in created:
        print(f"  #{al['id']} {al['taluk_name']} via {al['source']}: {al['message_en'][:90]}...")
