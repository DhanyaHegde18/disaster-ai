"""
Landslide model: the chance of a landslide in a rain-grid square in the next 3 days.

The SAME feature code is used for training (ml/training/train_landslide.py, on IMD history) and
live (on Open-Meteo forecasts scaled to IMD's level), so the model sees the same kind of numbers.

Features per square and day t
  rain_past_3d        rain on t-2..t            what has just fallen
  rain_past_7d        rain on t-6..t
  rain_past_15d       rain on t-14..t           how soaked the soil already is (antecedent rain)
  rain_next_3d        rain on t+1..t+3          forecast (training: what actually fell)
  rain_max_day_next3  wettest single day in t+1..t+3
  slope_p90           90th percentile slope in the square (degrees)    from ml/data/cell_terrain.csv
  steep_share         share of sampled spots steeper than 25 degrees
  relief              highest minus lowest point sampled (m)

Files written by training (absent = the app runs on the rain rule alone):
  backend/app/landslide_model.joblib   the fitted scikit-learn model
  backend/app/landslide_model.json     features, probability thresholds for MEDIUM/HIGH, metrics, terrain per square
"""
import json
from functools import lru_cache

from .. import config

FEATURES = ["rain_past_3d", "rain_past_7d", "rain_past_15d", "rain_next_3d", "rain_max_day_next3",
            "slope_p90", "steep_share", "relief"]
TERRAIN = ["slope_p90", "steep_share", "relief"]
PAST_DAYS_NEEDED = 15

MODEL_FILE = config.APP_DIR / "landslide_model.joblib"
META_FILE = config.APP_DIR / "landslide_model.json"


def log_rain(X):
    """Used inside the saved logistic-regression model (so it must live here, where the server can import it):
    rain amounts are very skewed, log(1 + mm) makes 10 -> 100 mm matter as much as 100 -> 1000 mm."""
    import numpy as np
    X = X.copy()
    cols = [c for c in X.columns if c.startswith("rain")]
    X[cols] = np.log1p(X[cols].clip(lower=0))
    return X


def rain_features(past: list[float], future: list[float]) -> dict:
    """past: daily rain ending with today (oldest first, up to 15 values); future: day +1..+3."""
    def last(n):
        return float(sum(past[-n:]))
    fut = list(future[:3])
    return {"rain_past_3d": last(3), "rain_past_7d": last(7), "rain_past_15d": last(15),
            "rain_next_3d": float(sum(fut)), "rain_max_day_next3": float(max(fut) if fut else 0.0)}


def table_features(daily, terrain):
    """Training: daily rain table (rows = days, columns = squares) -> long table of features per square-day.
    `terrain` is a DataFrame indexed by cell_id with the TERRAIN columns."""
    import pandas as pd

    parts = []
    for cell in daily.columns:
        if cell not in terrain.index:
            continue
        s = daily[cell]
        nxt = pd.concat([s.shift(-1), s.shift(-2), s.shift(-3)], axis=1)
        f = pd.DataFrame({
            "date": s.index, "cell_id": cell,
            "rain_past_3d": s.rolling(3, min_periods=3).sum().values,
            "rain_past_7d": s.rolling(7, min_periods=7).sum().values,
            "rain_past_15d": s.rolling(15, min_periods=15).sum().values,
            "rain_next_3d": nxt.sum(axis=1, min_count=3).values,
            "rain_max_day_next3": nxt.max(axis=1).where(nxt.notna().all(axis=1)).values,
        })
        for k in TERRAIN:
            f[k] = float(terrain.loc[cell, k])
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


@lru_cache
def _load(model_mtime: float, meta_mtime: float):
    import joblib
    return joblib.load(MODEL_FILE), json.loads(META_FILE.read_text())


load_error: str | None = None


def model():
    """(model, meta) or None when no model has been trained yet, or when it can't be loaded here (e.g. a server
    with a different scikit-learn version): then warnings fall back to the rain rule and /health says why."""
    global load_error
    if not (MODEL_FILE.exists() and META_FILE.exists()):
        return None
    try:
        loaded = _load(MODEL_FILE.stat().st_mtime, META_FILE.stat().st_mtime)
        load_error = None
        return loaded
    except Exception as err:
        if load_error is None:
            print(f"[landslide] model could not be loaded, using the rain rule only: {type(err).__name__}: {err}", flush=True)
        load_error = f"{type(err).__name__}: {str(err)[:160]}"
        return None


def level_for(prob: float, thresholds: dict) -> str:
    return "HIGH" if prob >= thresholds["high"] else "MEDIUM" if prob >= thresholds["medium"] else "LOW"


def predict_cells(rows: dict[str, dict]) -> dict[str, dict]:
    """rows: {cell_id: rain_features(...)} -> {cell_id: {"prob", "level"}} for squares with known terrain.
    Empty if there is no model."""
    loaded = model()
    if not loaded or not rows:
        return {}
    mdl, meta = loaded
    terrain = meta.get("terrain", {})
    ids = [c for c in rows if c in terrain]
    if not ids:
        return {}
    import pandas as pd
    X = pd.DataFrame([{**rows[c], **{k: terrain[c][k] for k in TERRAIN}} for c in ids], columns=meta["features"])
    probs = mdl.predict_proba(X)[:, 1]
    return {c: {"prob": round(float(p), 4), "level": level_for(float(p), meta["thresholds"])} for c, p in zip(ids, probs)}
