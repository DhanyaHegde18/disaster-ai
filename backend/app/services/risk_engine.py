"""
Rule-based warning engine (version 2: state-wide, per rain-grid square).

For each IMD 0.25 degree square (about 27 km):
  past_3d     = rain on day -2, day -1 and today
  forecast_3d = rain expected on day +1, +2, +3
Both are first scaled by the square's Open-Meteo bias factor for that month, so they're on
the level of the IMD gauge data the thresholds came from. Each measure gets LOW / MEDIUM / HIGH
from the square's own thresholds; the square's level is the higher of the two, and `reasons`
says which measure caused it. Every village in a square shares its level.

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


def assess_cell(cell_id: str, cell: dict, daily: list[tuple[date, float]], today: date) -> dict:
    """Risk for one square from its 6 daily values around `today`."""
    by_day = dict(daily)
    days = sorted(by_day)
    if today not in by_day:
        raise ValueError(f"{cell_id}: no value for today ({today}) in forecast")
    past_days = [d for d in days if d <= today][-3:]
    next_days = [d for d in days if d > today][:3]
    bias = cell.get("bias") or {}

    def scaled(d: date) -> float:
        return by_day[d] * float(bias.get(str(d.month), 1.0))

    past_3d = round(sum(scaled(d) for d in past_days), 1)
    forecast_3d = round(sum(scaled(d) for d in next_days), 1)
    lv_past = level_for(past_3d, cell["past_3d"])
    lv_fc = level_for(forecast_3d, cell["forecast_3d"])
    level = max(lv_past, lv_fc, key=LEVELS.index)

    reasons = []
    if lv_past != "LOW":
        reasons.append(f"Last 3 days: {past_3d} mm (≥ {cell['past_3d'][lv_past.lower()]} mm is {lv_past} here)")
    if lv_fc != "LOW":
        reasons.append(f"Next 3 days forecast: {forecast_3d} mm (≥ {cell['forecast_3d'][lv_fc.lower()]} mm is {lv_fc} here)")
    if not reasons:
        reasons.append("Rainfall below warning thresholds")

    return {
        "cell_id": cell_id,
        "lat": cell["lat"],
        "lon": cell["lon"],
        "level": level,
        "past_3d_mm": past_3d,
        "forecast_3d_mm": forecast_3d,
        "reasons": reasons,
        "daily_mm": [{"date": d.isoformat(), "rain_mm": round(scaled(d), 1),
                      "kind": "observed" if d < today else ("today" if d == today else "forecast")}
                     for d in past_days + next_days],
    }


def scaled_split(cell: dict, daily: list[tuple[date, float]], today: date) -> tuple[list[float], list[float]]:
    """(past days up to today, next 3 days) of bias-scaled rain, for the landslide model."""
    bias = cell.get("bias") or {}
    s = {d: v * float(bias.get(str(d.month), 1.0)) for d, v in daily}
    days = sorted(s)
    return [s[d] for d in days if d <= today], [s[d] for d in days if d > today][:3]


def add_landslide(result: dict, ls: dict | None, budgets: dict) -> dict:
    """Merge the landslide model's view into a square's result: the level is the higher of the two."""
    if not ls:
        return result
    result["landslide_prob"], result["landslide_level"] = ls["prob"], ls["level"]
    if ls["level"] != "LOW":
        share = budgets.get(ls["level"].lower(), 0)
        result["reasons"] = [r for r in result["reasons"] if r != "Rainfall below warning thresholds"]
        result["reasons"].append(f"Landslide model: {ls['level']} (among the riskiest {share:.1%} of past monsoon days, "
                                 f"from slope, soaked soil and coming rain)")
        if LEVELS.index(ls["level"]) > LEVELS.index(result["level"]):
            result["level"] = ls["level"]
    return result


def assess_all(daily_by_cell: dict, today: date, grid: dict, landslide_by_cell: dict | None = None,
               budgets: dict | None = None) -> list[dict]:
    results = [add_landslide(assess_cell(cid, c, daily_by_cell[cid], today), (landslide_by_cell or {}).get(cid), budgets or {})
               for cid, c in grid["cells"].items() if cid in daily_by_cell]
    # Most urgent first: HIGH, then MEDIUM, then LOW; wetter forecast first within a level.
    results.sort(key=lambda r: (-LEVELS.index(r["level"]), -r["forecast_3d_mm"]))
    return results
