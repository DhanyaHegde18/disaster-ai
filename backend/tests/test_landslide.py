"""The landslide model in the live app: features, prediction, merging with the rain rule."""
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from backend.app.services import landslide, risk_engine
from backend.tests.conftest import app_client, sign_in

STEEP, FLAT = "12.75_75.50", "13.25_74.75"       # Subramanya's square is steep; Kukkehalli's is flat


def test_rain_features():
    f = landslide.rain_features([1.0] * 15, [10.0, 40.0, 5.0])
    assert f == {"rain_past_3d": 3.0, "rain_past_7d": 7.0, "rain_past_15d": 15.0,
                 "rain_next_3d": 55.0, "rain_max_day_next3": 40.0}
    short = landslide.rain_features([2.0, 2.0], [1.0])           # fewer days than asked: uses what it has
    assert short["rain_past_15d"] == 4.0 and short["rain_next_3d"] == 1.0


def test_table_features_match_live_features():
    days = pd.date_range("2018-07-01", periods=25)
    rain = np.arange(25, dtype=float)
    t = landslide.table_features(pd.DataFrame({"c": rain}, index=days),
                                 pd.DataFrame({"slope_p90": [30.0], "steep_share": [0.4], "relief": [800.0]}, index=["c"]))
    row = t[t["date"] == days[20]].iloc[0]
    live = landslide.rain_features(list(rain[6:21]), list(rain[21:24]))
    for k, v in live.items():
        assert row[k] == pytest.approx(v), k


@pytest.fixture
def trained(world):
    """A small real model: landslides when it's steep AND soaked AND more rain is coming."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler
    rng = np.random.default_rng(0)
    n = 4000
    X = pd.DataFrame({"rain_past_3d": rng.gamma(1, 30, n), "rain_past_7d": rng.gamma(1, 70, n),
                      "rain_past_15d": rng.gamma(1, 150, n), "rain_next_3d": rng.gamma(1, 40, n),
                      "rain_max_day_next3": rng.gamma(1, 20, n), "slope_p90": rng.uniform(2, 40, n),
                      "steep_share": rng.uniform(0, 0.6, n), "relief": rng.uniform(20, 1500, n)})
    y = ((X.slope_p90 > 25) & (X.rain_past_15d > 250) & (X.rain_next_3d > 60)).astype(int)
    m = make_pipeline(FunctionTransformer(landslide.log_rain), StandardScaler(),
                      LogisticRegression(max_iter=2000)).fit(X[landslide.FEATURES], y)
    joblib.dump(m, landslide.MODEL_FILE)
    landslide.META_FILE.write_text(json.dumps({
        "model": "logistic", "created": "2026-10-24", "years": [2016, 2020], "features": landslide.FEATURES,
        "thresholds": {"medium": 0.3, "high": 0.6}, "budgets": {"medium": 0.02, "high": 0.005},
        "terrain": {STEEP: {"slope_p90": 35.0, "steep_share": 0.5, "relief": 1200.0},
                    FLAT: {"slope_p90": 4.0, "steep_share": 0.0, "relief": 60.0}}}))
    return world


def test_no_model_means_rain_rule_only(world):
    with app_client() as c:
        sign_in(c, taluk_id=None)
        r = c.get("/risk").json()
        assert world.asked_past_days == 2                       # no need to download 15 days
        assert all("landslide_level" not in cell for cell in r["cells"])
        assert c.get("/health").json()["landslide_model"] == "not trained yet (rain rule only)"


def test_model_alone_only_raises_to_medium_by_default(trained):
    for cell in (STEEP, FLAT):
        trained.rain(cell, past=60, future=90, soaked=400)       # rain rule: LOW (below 100 mm)
    with app_client() as c:
        sign_in(c, taluk_id=None)
        cells = {x["cell_id"]: x for x in c.get("/risk").json()["cells"]}
        assert cells[STEEP]["landslide_level"] == "HIGH" and cells[STEEP]["level"] == "MEDIUM"
        assert any("until the rain rule agrees" in s for s in cells[STEEP]["reasons"])
        assert cells[FLAT]["level"] == "LOW"
        assert c.post("/alerts/generate").json()["created"] == 0               # watch, no alert draft


def test_model_and_rule_together_make_high(trained):
    trained.rain(STEEP, past=110, future=90, soaked=400)        # rain rule: MEDIUM (past 3 days >= 100 mm)
    with app_client() as c:
        sign_in(c, taluk_id=None)
        cell = next(x for x in c.get("/risk").json()["cells"] if x["cell_id"] == STEEP)
    assert cell["level"] == "HIGH" and not any("until the rain rule agrees" in s for s in cell["reasons"])


def test_model_raises_steep_soaked_square(trained, monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config, "LANDSLIDE_MODEL_ALONE_MAX", "HIGH")       # trust the model on its own
    # same moderate rain on both squares: below the rain rule's thresholds (MEDIUM 100 mm)
    for cell in (STEEP, FLAT):
        trained.rain(cell, past=60, future=90, soaked=400)
    with app_client() as c:
        sign_in(c, taluk_id=None)
        r = c.get("/risk").json()
        assert trained.asked_past_days == landslide.PAST_DAYS_NEEDED
        cells = {x["cell_id"]: x for x in r["cells"]}
        assert cells[STEEP]["level"] == "HIGH" and cells[STEEP]["landslide_level"] == "HIGH"
        assert any(s.startswith("Landslide model: HIGH") for s in cells[STEEP]["reasons"])
        assert cells[FLAT]["level"] == "LOW" and cells[FLAT]["landslide_level"] == "LOW"
        sullia = next(t for t in r["taluks"] if t["taluk_id"] == "dakshina-kannada:sullia")
        assert sullia["level"] == "HIGH" and sullia["landslide_level"] == "HIGH"
        assert "logistic, trained 2026-10-24" in c.get("/health").json()["landslide_model"]
        a = c.post("/alerts/generate").json()["alerts"]
        assert [x["taluk_name"] for x in a] == ["Sullia"]        # the landslide model alone triggered an alert


def test_dry_steep_square_stays_low(trained):
    trained.rain(STEEP, past=5, future=5, soaked=20)
    with app_client() as c:
        sign_in(c, taluk_id=None)
        cell = next(x for x in c.get("/risk").json()["cells"] if x["cell_id"] == STEEP)
    assert cell["level"] == "LOW" and cell["landslide_level"] == "LOW"


def test_rule_level_is_never_lowered_by_the_model():
    r = {"level": "HIGH", "reasons": ["Next 3 days forecast: 300 mm"]}
    out = risk_engine.add_landslide(r, {"prob": 0.01, "level": "LOW"}, {"medium": 0.02, "high": 0.005})
    assert out["level"] == "HIGH" and out["landslide_level"] == "LOW"
