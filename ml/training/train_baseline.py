"""
Phase 2, step 1: a baseline early-warning model (logistic regression).

Input : ml/data/processed/training_table.csv   (from build_features.py)
Output: ml/models/baseline.pkl                  (model + feature list + alert threshold)
        printed evaluation report

Why logistic regression first?
  It is simple, fast and explainable. Any fancier model later (XGBoost, LSTM)
  must beat it, otherwise the extra complexity is not worth it.

How it is evaluated (read this, it matters more than the code)
  * Time split, never random: train on the past, test on the future.
    A random split would leak information from the same storm into both sides.
  * Positives are rare (< 0.1% of rows), so accuracy is meaningless:
    predicting "no disaster" every day already scores 99.9%.
    We use PR-AUC and, most importantly, EVENT RECALL:
    "for each real event in the test years, did the model raise an alert
    on at least one of the days before it?"
  * Alerts have a cost too, so we report how many alert-days per village per
    monsoon the threshold produces. A model that alerts every day is useless.
  * Compared against a plain rainfall rule (alert when 3-day rain is very high),
    which is what your hackathon version effectively did.

Run from the project root:
    python ml/training/train_baseline.py --test-from 2024-01-01
"""
import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ML_DIR = Path(__file__).resolve().parents[1]
TABLE = ML_DIR / "data" / "processed" / "training_table.csv"
EVENTS = ML_DIR / "data" / "events.csv"
MODEL_OUT = ML_DIR / "models" / "baseline.pkl"

RAIN_FEATURES = ["rain_1d", "rain_3d", "rain_7d", "rain_14d", "rain_30d",
                 "rain_max_7d", "wet_streak_days", "is_monsoon"]
TERRAIN_FEATURES = ["elevation_m", "slope_deg", "mean_slope_deg",
                    "p90_slope_deg", "max_slope_deg", "relief_m"]


def event_recall(test: pd.DataFrame, alert: np.ndarray, test_from: str) -> tuple[int, int, list]:
    """How many real test-period events had an alert on one of the days before them."""
    events = pd.read_csv(EVENTS, parse_dates=["date"])
    events = events[events["date"] >= test_from]
    test = test.assign(alert=alert)
    caught, rows = 0, []
    for e in events.itertuples(index=False):
        window = test[(test["village_id"] == e.village_id)
                      & (test["date"] < e.date)
                      & (test["date"] >= e.date - pd.Timedelta(days=3))]
        hit = bool(window["alert"].any())
        caught += hit
        rows.append((e.village_id, e.date.date(), e.event_type, "CAUGHT" if hit else "missed"))
    return caught, len(events), rows


def alerts_per_monsoon(test: pd.DataFrame, alert: np.ndarray) -> float:
    """Average alert-days per village per monsoon season (Jun–Sep) in the test period."""
    monsoon = test["is_monsoon"] == 1
    seasons = test.loc[monsoon, "date"].dt.year.nunique()
    villages = test["village_id"].nunique()
    return alert[monsoon.to_numpy()].sum() / max(seasons * villages, 1)


def report(name, test, scores, alert, test_from):
    y = test["label"].to_numpy()
    caught, total, rows = event_recall(test, alert, test_from)
    print(f"\n=== {name} ===")
    if y.sum() > 0:
        print(f"PR-AUC  : {average_precision_score(y, scores):.3f}   "
              f"(random guessing would score about {y.mean():.4f})")
        print(f"ROC-AUC : {roc_auc_score(y, scores):.3f}")
    print(f"Event recall : {caught}/{total} events had an alert in the 3 days before")
    print(f"Alert load   : {alerts_per_monsoon(test, alert):.1f} alert-days per village per monsoon")
    for r in rows:
        print(f"   {r[0]} {r[1]} {r[2]:<9} {r[3]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-from", default="2024-01-01",
                        help="rows on/after this date are the test set (default 2024-01-01)")
    parser.add_argument("--alert-rate", type=float, default=0.05,
                        help="alert on the riskiest X of monsoon days, set on TRAINING data (default 0.05 = 5%%)")
    args = parser.parse_args()

    df = pd.read_csv(TABLE, parse_dates=["date"])
    features = RAIN_FEATURES + [c for c in TERRAIN_FEATURES if c in df.columns]
    missing_terrain = [c for c in TERRAIN_FEATURES if c not in df.columns]
    if missing_terrain:
        print(f"note: terrain columns not found, training on rainfall only: {missing_terrain}")

    train = df[df["date"] < args.test_from]
    test = df[df["date"] >= args.test_from]
    print(f"train: {len(train):,} rows, {int(train['label'].sum())} positive  "
          f"({train['date'].min().date()} to {train['date'].max().date()})")
    print(f"test : {len(test):,} rows, {int(test['label'].sum())} positive  "
          f"({test['date'].min().date()} to {test['date'].max().date()})")
    if train["label"].sum() == 0:
        raise SystemExit("No positive rows in the training period. Add events or move --test-from.")

    # class_weight="balanced" makes each rare positive row count as much as
    # hundreds of normal days, so the model can't just predict "never".
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=2000, C=0.1),
    )
    model.fit(train[features], train["label"])

    # Pick the alert threshold on TRAINING monsoon days only, never on test data.
    train_scores = model.predict_proba(train[features])[:, 1]
    monsoon_train = train["is_monsoon"].to_numpy() == 1
    threshold = float(np.quantile(train_scores[monsoon_train], 1 - args.alert_rate))

    test_scores = model.predict_proba(test[features])[:, 1]
    report("Logistic regression", test, test_scores, test_scores >= threshold, args.test_from)

    # Baseline to beat: alert when 3-day rain is in the top X% of training monsoon days.
    rule_threshold = float(np.quantile(train.loc[monsoon_train, "rain_3d"], 1 - args.alert_rate))
    rule_alert = test["rain_3d"].to_numpy() >= rule_threshold
    report(f"Rainfall rule (rain_3d >= {rule_threshold:.0f} mm)", test,
           test["rain_3d"].to_numpy(), rule_alert, args.test_from)

    # Which features push risk up or down (on the standardised scale).
    coefs = model.named_steps["logisticregression"].coef_[0]
    print("\nFeature weights (positive = raises risk):")
    for name, w in sorted(zip(features, coefs), key=lambda t: -abs(t[1])):
        print(f"   {name:<16} {w:+.2f}")

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_OUT, "wb") as f:
        pickle.dump({"model": model, "features": features, "threshold": threshold}, f)
    print(f"\nsaved {MODEL_OUT.relative_to(ML_DIR.parent)}")


if __name__ == "__main__":
    main()