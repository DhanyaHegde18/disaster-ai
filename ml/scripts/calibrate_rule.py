"""
Phase 3, step 0: calibrate the rule-based warning engine from your own history.

The cross-validation showed a simple rainfall rule beats the ML model for now.
This script turns that rule into the backend's config:

  Thresholds (from monsoon days in ml/data/processed/training_table.csv)
    past_3d_mm      rain over the last 3 days (today included)
    forecast_3d_mm  rain expected over the next 3 days
    HIGH   = the wettest 5%  of monsoon days for that measure
    MEDIUM = the wettest 15% of monsoon days for that measure
  A village's level is the higher of its two levels (past or forecast).

  It also copies into the config what the backend needs and git won't have
  (ml/data/raw is git-ignored): the village list and the Open-Meteo bias factors,
  so live Open-Meteo values are scaled to the same level as your training data.

  Finally it replays the rule over history: for each real event, what level did
  the rule reach in the 3 days before it? That's your sanity check.

Input : ml/data/processed/training_table.csv   (build with --rain-dir rainfall_merged)
        ml/data/villages.csv, ml/data/events.csv
        ml/data/raw/rainfall_merged/_bias_factors.csv   (from merge_rainfall.py)
Output: backend/app/rule_config.json

Run from the project root:
    python ml/scripts/calibrate_rule.py
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml" / "data"
TABLE = DATA / "processed" / "training_table.csv"
BIAS = DATA / "raw" / "rainfall_merged" / "_bias_factors.csv"
OUT = ROOT / "backend" / "app" / "rule_config.json"
LEVELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def level_for(value: float, t: dict) -> str:
    if value >= t["high"]:
        return "HIGH"
    if value >= t["medium"]:
        return "MEDIUM"
    return "LOW"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--high-rate", type=float, default=0.05, help="share of monsoon days that are HIGH")
    p.add_argument("--medium-rate", type=float, default=0.15, help="share of monsoon days at MEDIUM or above")
    args = p.parse_args()

    df = pd.read_csv(TABLE, parse_dates=["date"])
    for col in ("rain_3d", "fc_rain_3d"):
        if col not in df.columns:
            raise SystemExit(f"'{col}' missing. Rebuild: python ml/scripts/build_features.py --rain-dir rainfall_merged")
    monsoon = df[df["is_monsoon"] == 1]

    def thresholds(col: str) -> dict:
        return {"medium": round(float(monsoon[col].quantile(1 - args.medium_rate)), 1),
                "high": round(float(monsoon[col].quantile(1 - args.high_rate)), 1)}

    past_t, fc_t = thresholds("rain_3d"), thresholds("fc_rain_3d")

    # Replay the rule over history.
    lv_past = df["rain_3d"].apply(lambda v: LEVELS[level_for(v, past_t)])
    lv_fc = df["fc_rain_3d"].apply(lambda v: LEVELS[level_for(v, fc_t)])
    df["level"] = pd.concat([lv_past, lv_fc], axis=1).max(axis=1)
    names = {v: k for k, v in LEVELS.items()}

    events = pd.read_csv(DATA / "events.csv", parse_dates=["date"])
    replay = []
    for e in events.itertuples(index=False):
        w = df[(df["village_id"] == e.village_id) & (df["date"] < e.date)
               & (df["date"] >= e.date - pd.Timedelta(days=3))]
        best = names[int(w["level"].max())] if len(w) else "NO DATA"
        replay.append({"village_id": e.village_id, "date": str(e.date.date()),
                       "type": e.event_type, "level_before": best})

    seasons = monsoon["date"].dt.year.nunique() * monsoon["village_id"].nunique()
    m_levels = df.loc[df["is_monsoon"] == 1, "level"]
    load = {"high_days_per_village_per_monsoon": round(float((m_levels == 2).sum() / seasons), 1),
            "medium_or_high_days_per_village_per_monsoon": round(float((m_levels >= 1).sum() / seasons), 1)}

    villages = pd.read_csv(DATA / "villages.csv")
    if BIAS.exists():
        b = pd.read_csv(BIAS)
        bias = {vid: {str(int(r.month)): float(r.factor) for r in g.itertuples()} for vid, g in b.groupby("village_id")}
    else:
        print(f"note: {BIAS} not found, so live Open-Meteo values are used unscaled (factor 1.0)")
        bias = {}

    config = {
        "calibrated_on": str(date.today()),
        "source_table": "ml/data/processed/training_table.csv",
        "rule": "level = higher of (past 3-day rain level, forecast 3-day rain level)",
        "thresholds_mm": {"past_3d": past_t, "forecast_3d": fc_t},
        "monsoon_alert_rates": {"medium_or_high": args.medium_rate, "high": args.high_rate},
        "historical_alert_load": load,
        "villages": villages[[c for c in ["village_id", "name", "name_kn", "district", "lat", "lon"] if c in villages.columns]].to_dict(orient="records"),
        "bias_factors": bias,
        "event_replay": replay,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(config, indent=2))

    print(f"Thresholds (mm)      MEDIUM   HIGH")
    print(f"  past 3 days      {past_t['medium']:>8} {past_t['high']:>6}")
    print(f"  next 3 days      {fc_t['medium']:>8} {fc_t['high']:>6}")
    print(f"\nAlert load: {load['high_days_per_village_per_monsoon']} HIGH days and "
          f"{load['medium_or_high_days_per_village_per_monsoon']} MEDIUM-or-HIGH days per village per monsoon")
    print("\nReplay: highest level in the 3 days before each event")
    for r in replay:
        print(f"  {r['village_id']} {r['date']} {r['type']:<9} {r['level_before']}")
    counts = pd.Series([r["level_before"] for r in replay]).value_counts()
    print(f"\n  HIGH {counts.get('HIGH', 0)}   MEDIUM {counts.get('MEDIUM', 0)}   LOW {counts.get('LOW', 0)}   "
          f"(of {len(replay)} events)")
    print(f"\nsaved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
