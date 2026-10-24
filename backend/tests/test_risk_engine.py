"""The rule, per rain-grid square (pure functions, no network)."""
from datetime import date, timedelta

from backend.app.services.risk_engine import assess_all, assess_cell, level_for

TODAY = date(2026, 8, 5)
CELL = {"lat": 13.0, "lon": 75.25, "past_3d": {"medium": 100, "high": 150},
        "forecast_3d": {"medium": 120, "high": 180}, "bias": {"8": 2.0}}


def days(values):
    return [(TODAY + timedelta(days=i - 2), v) for i, v in enumerate(values)]


def test_levels():
    t = {"medium": 100, "high": 150}
    assert [level_for(v, t) for v in (99.9, 100, 149.9, 150)] == ["LOW", "MEDIUM", "MEDIUM", "HIGH"]


def test_bias_scales_both_measures_and_level_is_the_higher():
    r = assess_cell("13.00_75.25", CELL, days([10, 10, 10, 30, 30, 30]), TODAY)
    assert (r["past_3d_mm"], r["forecast_3d_mm"]) == (60.0, 180.0)        # x2 for August
    assert r["level"] == "HIGH" and "forecast" in r["reasons"][0].lower()
    assert [d["kind"] for d in r["daily_mm"]] == ["observed", "observed", "today", "forecast", "forecast", "forecast"]


def test_no_bias_for_other_months():
    sept = date(2026, 9, 10)
    r = assess_cell("c", CELL, [(sept + timedelta(days=i - 2), 10) for i in range(6)], sept)
    assert r["past_3d_mm"] == 30.0 and r["level"] == "LOW" and r["reasons"] == ["Rainfall below warning thresholds"]


def test_missing_today_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        assess_cell("c", CELL, days([1] * 6)[3:], TODAY)


def test_assess_all_most_urgent_first():
    grid = {"cells": {"a": CELL, "b": CELL, "c": CELL}}
    daily = {"a": days([1] * 6), "b": days([60, 60, 60, 0, 0, 0]), "c": days([0, 0, 0, 40, 40, 40])}
    out = assess_all(daily, TODAY, grid)
    assert [r["cell_id"] for r in out] == ["c", "b", "a"] and [r["level"] for r in out] == ["HIGH", "HIGH", "LOW"]
