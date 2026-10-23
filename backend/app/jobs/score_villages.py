"""
Score every village now and save the result to backend/data/latest_risk.json.

The API calls the same function when its cache is old, and you can run it on a
schedule (cron, or GitHub Actions later) to keep results fresh.

Run from the project root:
    python -m backend.app.jobs.score_villages
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import config
from ..services.forecast import fetch_daily_rain
from ..services.risk_engine import assess_all


def score_now() -> dict:
    cfg = config.rule_config()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    daily = fetch_daily_rain(cfg["villages"])
    results = assess_all(daily, now.date(), cfg)
    snapshot = {
        "generated_at": now.isoformat(timespec="seconds"),
        "engine": "rule-v1",
        "thresholds_mm": cfg["thresholds_mm"],
        "calibrated_on": cfg["calibrated_on"],
        "summary": {lv: sum(r["level"] == lv for r in results) for lv in ("HIGH", "MEDIUM", "LOW")},
        "villages": results,
    }
    config.LATEST_RISK_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.LATEST_RISK_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    return snapshot


if __name__ == "__main__":
    s = score_now()
    print(f"generated {s['generated_at']}   HIGH {s['summary']['HIGH']}  "
          f"MEDIUM {s['summary']['MEDIUM']}  LOW {s['summary']['LOW']}")
    for r in s["villages"]:
        print(f"  {r['village_id']} {r['name']:<12} {r['level']:<6} "
              f"past 3d {r['past_3d_mm']:>6} mm   next 3d {r['forecast_3d_mm']:>6} mm")
    print(f"saved {config.LATEST_RISK_FILE}")

    # Draft alerts for HIGH villages (skipped for villages that already have one today).
    from .. import database
    from ..services.alerts import generate_for_snapshot
    database.init_db()
    created = generate_for_snapshot(s)
    print(f"alerts drafted: {len(created)}")
    for a in created:
        print(f"  #{a['id']} {a['village_name']} via {a['source']}: {a['message_en'][:90]}...")
