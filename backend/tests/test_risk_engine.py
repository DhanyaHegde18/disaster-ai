"""Tests for the rule engine. Run from the project root:  pytest backend/tests -v"""
from datetime import date, timedelta

import pytest

from backend.app.services.risk_engine import assess_all, assess_village, level_for

CFG = {
    "thresholds_mm": {"past_3d": {"medium": 100.0, "high": 200.0},
                      "forecast_3d": {"medium": 120.0, "high": 250.0}},
    "villages": [{"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada"},
                 {"village_id": "V002", "name": "Belthangady", "district": "Dakshina Kannada"}],
    "bias_factors": {"V001": {"7": 2.0, "8": 2.0}},  # day -2 and -1 fall in July
}
TODAY = date(2026, 8, 1)


def series(values):
    """6 daily values: day -2 .. day +3."""
    return [(TODAY + timedelta(days=i - 2), v) for i, v in enumerate(values)]


def test_level_boundaries():
    t = {"medium": 100, "high": 200}
    assert level_for(99.9, t) == "LOW"
    assert level_for(100, t) == "MEDIUM"
    assert level_for(200, t) == "HIGH"


def test_dry_village_is_low():
    r = assess_village(CFG["villages"][1], series([1, 2, 3, 4, 5, 6]), TODAY, CFG)
    assert r["level"] == "LOW"
    assert r["past_3d_mm"] == 6 and r["forecast_3d_mm"] == 15


def test_forecast_alone_can_raise_high():
    r = assess_village(CFG["villages"][1], series([0, 0, 0, 100, 100, 100]), TODAY, CFG)
    assert r["level"] == "HIGH"
    assert any("forecast" in x for x in r["reasons"])


def test_level_is_the_higher_of_past_and_forecast():
    r = assess_village(CFG["villages"][1], series([50, 50, 50, 50, 50, 50]), TODAY, CFG)
    assert r["level"] == "MEDIUM"  # past 150 -> MEDIUM, forecast 150 -> MEDIUM


def test_bias_factor_is_applied():
    # V001 has July and August factors of 2.0: 3 x 40 mm becomes 240 mm -> HIGH on past rain.
    r = assess_village(CFG["villages"][0], series([40, 40, 40, 0, 0, 0]), TODAY, CFG)
    assert r["past_3d_mm"] == 240
    assert r["level"] == "HIGH"


def test_missing_today_raises():
    bad = [(TODAY + timedelta(days=5), 1.0)]
    with pytest.raises(ValueError):
        assess_village(CFG["villages"][1], bad, TODAY, CFG)


def test_results_sorted_most_urgent_first():
    out = assess_all({"V001": series([0] * 6), "V002": series([0, 0, 0, 100, 100, 100])}, TODAY, CFG)
    assert [r["village_id"] for r in out] == ["V002", "V001"]
