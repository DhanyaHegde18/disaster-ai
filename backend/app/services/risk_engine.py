"""
Rule-based warning engine (version 1).

  past_3d     = rain on day -2, day -1 and today
  forecast_3d = rain expected on day +1, +2, +3
Both are first scaled by the village's Open-Meteo bias factor for that month,
so they're on the same level as the data the thresholds were calibrated on.
Each measure gets LOW / MEDIUM / HIGH from its thresholds; the village's level
is the higher of the two, and `reasons` says which measure caused it.

Pure functions, no network: easy to test (see backend/tests/test_risk_engine.py).
"""
from datetime import date

LEVELS = ["LOW", "MEDIUM", "HIGH"]


def level_for(value_mm: float, thresholds: dict) -> str:
    if value_mm >= thresholds["high"]:
        return "HIGH"
    if value_mm >= thresholds["medium"]:
        return "MEDIUM"
    return "LOW"


def bias_factor(cfg: dict, village_id: str, month: int) -> float:
    return float(cfg.get("bias_factors", {}).get(village_id, {}).get(str(month), 1.0))


def assess_village(village: dict, daily: list[tuple[date, float]], today: date, cfg: dict) -> dict:
    """Risk for one village from its 6 daily values around `today`."""
    by_day = dict(daily)
    days = sorted(by_day)
    if today not in by_day:
        raise ValueError(f"{village['village_id']}: no value for today ({today}) in forecast")
    past_days = [d for d in days if d <= today][-3:]
    next_days = [d for d in days if d > today][:3]

    def scaled(d: date) -> float:
        return by_day[d] * bias_factor(cfg, village["village_id"], d.month)

    past_3d = round(sum(scaled(d) for d in past_days), 1)
    forecast_3d = round(sum(scaled(d) for d in next_days), 1)

    t = cfg["thresholds_mm"]
    lv_past = level_for(past_3d, t["past_3d"])
    lv_fc = level_for(forecast_3d, t["forecast_3d"])
    level = max(lv_past, lv_fc, key=LEVELS.index)

    reasons = []
    if lv_past != "LOW":
        reasons.append(f"Last 3 days: {past_3d} mm (≥ {t['past_3d'][lv_past.lower()]} mm is {lv_past})")
    if lv_fc != "LOW":
        reasons.append(f"Next 3 days forecast: {forecast_3d} mm (≥ {t['forecast_3d'][lv_fc.lower()]} mm is {lv_fc})")
    if not reasons:
        reasons.append("Rainfall below warning thresholds")

    return {
        "village_id": village["village_id"],
        "name": village["name"],
        "district": village["district"],
        "level": level,
        "past_3d_mm": past_3d,
        "forecast_3d_mm": forecast_3d,
        "reasons": reasons,
        "daily_mm": [{"date": d.isoformat(), "rain_mm": round(scaled(d), 1),
                      "kind": "observed" if d < today else ("today" if d == today else "forecast")}
                     for d in past_days + next_days],
    }


def assess_all(daily_by_village: dict, today: date, cfg: dict) -> list[dict]:
    results = []
    for v in cfg["villages"]:
        if v["village_id"] in daily_by_village:
            results.append(assess_village(v, daily_by_village[v["village_id"]], today, cfg))
    # Most urgent first: HIGH, then MEDIUM, then LOW; wetter forecast first within a level.
    results.sort(key=lambda r: (-LEVELS.index(r["level"]), -r["forecast_3d_mm"]))
    return results
