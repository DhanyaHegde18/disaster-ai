"""
Phase 2, step 2: leave-one-year-out cross-validation.

Why
  A single train/test split put only 4 events (one night in 2026) in the test set,
  so one bad night decided everything. Here every year takes a turn as the test
  year while the model trains on all the other years. Every event gets tested
  exactly once, by a model that never saw that year.

  Training on years AFTER the test year is fine here: we are measuring how well
  the method generalises to an unseen monsoon, and rain physics doesn't change
  between years. (For a final "would it have worked live?" check, keep a strict
  past-only split as well.)

Options
  --features rain        rainfall features only
  --features all         rainfall + terrain (terrain may just memorise villages)
  --forecast             add rain over the next 1-3 days. In training this is the
                         rain that actually fell (a perfect forecast), so treat the
                         result as an UPPER BOUND on what forecasts could add.

Run from the project root, e.g.:
    python ml/training/train_cv.py --features rain
    python ml/training/train_cv.py --features rain --forecast
    python ml/training/train_cv.py --features all  --forecast
"""
import argparse
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

RAIN = ["rain_1d", "rain_3d", "rain_7d", "rain_14d", "rain_30d",
        "rain_max_7d", "wet_streak_days", "is_monsoon"]
FORECAST = ["fc_rain_1d", "fc_rain_2d", "fc_rain_3d"]
TERRAIN = ["elevation_m", "slope_deg", "mean_slope_deg",
           "p90_slope_deg", "max_slope_deg", "relief_m"]
LEAD_DAYS = 3  # an event counts as caught if an alert fired on any of the 3 days before it


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--features", choices=["rain", "all"], default="rain")
    p.add_argument("--forecast", action="store_true")
    p.add_argument("--alert-rate", type=float, default=0.05,
                   help="alert on the riskiest X of monsoon days in the training years (default 0.05)")
    args = p.parse_args()

    df = pd.read_csv(TABLE, parse_dates=["date"])
    feats = list(RAIN)
    if args.forecast:
        missing = [c for c in FORECAST if c not in df.columns]
        if missing:
            raise SystemExit(f"{missing} not in the table. Re-run build_features.py with the latest version.")
        feats += FORECAST
    if args.features == "all":
        feats += [c for c in TERRAIN if c in df.columns]
    print(f"features ({len(feats)}): {', '.join(feats)}")

    df["year"] = df["date"].dt.year
    df["score_model"] = np.nan
    df["alert_model"] = False
    df["alert_rule"] = False
    rule_col = "fc_rain_3d" if args.forecast else "rain_3d"

    for year in sorted(df["year"].unique()):
        train, test_mask = df[df["year"] != year], df["year"] == year
        if train["label"].sum() == 0:
            continue
        model = make_pipeline(StandardScaler(),
                              LogisticRegression(class_weight="balanced", max_iter=2000, C=0.1))
        model.fit(train[feats], train["label"])
        last_fold = year

        monsoon = train["is_monsoon"] == 1
        thr = np.quantile(model.predict_proba(train.loc[monsoon, feats])[:, 1], 1 - args.alert_rate)
        scores = model.predict_proba(df.loc[test_mask, feats])[:, 1]
        df.loc[test_mask, "score_model"] = scores
        df.loc[test_mask, "alert_model"] = scores >= thr

        # Same rule as before, but its threshold also comes from the training years only.
        rule_thr = np.quantile(train.loc[monsoon, rule_col], 1 - args.alert_rate)
        df.loc[test_mask, "alert_rule"] = df.loc[test_mask, rule_col] >= rule_thr

    y = df["label"].to_numpy()
    print(f"\nPooled over all held-out years ({int(y.sum())} positive rows):")
    print(f"  model PR-AUC {average_precision_score(y, df['score_model']):.3f}  "
          f"ROC-AUC {roc_auc_score(y, df['score_model']):.3f}  "
          f"(random PR-AUC ~ {y.mean():.4f})")
    print(f"  rule  PR-AUC {average_precision_score(y, df[rule_col]):.3f}  "
          f"ROC-AUC {roc_auc_score(y, df[rule_col]):.3f}   [rule = {rule_col}]")

    events = pd.read_csv(EVENTS, parse_dates=["date"])
    print(f"\nPer event (caught = alert on one of the {LEAD_DAYS} days before):")
    caught = {"model": 0, "rule": 0}
    for e in events.itertuples(index=False):
        w = df[(df["village_id"] == e.village_id) & (df["date"] < e.date)
               & (df["date"] >= e.date - pd.Timedelta(days=LEAD_DAYS))]
        m, r = bool(w["alert_model"].any()), bool(w["alert_rule"].any())
        caught["model"] += m
        caught["rule"] += r
        peak = w["score_model"].max()
        print(f"  {e.village_id} {e.date.date()} {e.event_type:<9} "
              f"model {'CAUGHT' if m else 'missed':<6}  rule {'CAUGHT' if r else 'missed':<6}  "
              f"peak risk {peak:.2f}")

    mons = df["is_monsoon"] == 1
    seasons = df.loc[mons, "year"].nunique() * df["village_id"].nunique()
    n = len(events)
    print(f"\nEvent recall : model {caught['model']}/{n}   rule {caught['rule']}/{n}")
    print(f"Alert load   : model {df.loc[mons, 'alert_model'].sum() / seasons:.1f}   "
          f"rule {df.loc[mons, 'alert_rule'].sum() / seasons:.1f}   alert-days per village per monsoon")

    coefs = model.named_steps["logisticregression"].coef_[0]
    print(f"\nFeature weights (last fold, {last_fold} held out):")
    for name, w in sorted(zip(feats, coefs), key=lambda t: -abs(t[1])):
        print(f"  {name:<16} {w:+.2f}")


if __name__ == "__main__":
    main()
