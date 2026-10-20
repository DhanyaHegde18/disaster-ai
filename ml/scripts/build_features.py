"""
Phase 1, step 2: turn raw rainfall + event records into an ML training table.

Inputs
  ml/data/villages.csv            village_id, name, district, lat, lon
  ml/data/raw/rainfall/*.csv      from fetch_rainfall.py
  ml/data/events.csv              village_id, date, event_type   (you fill this in)
  ml/data/village_static.csv      OPTIONAL: village_id + any fixed features
                                  (slope_deg, elevation_m, dist_river_km, soil_type ...)

Output
  ml/data/processed/training_table.csv
  One row per village per day. Features use ONLY rainfall up to and including
  that day. The label says whether an event happened in the NEXT `horizon` days.
  That framing is what makes it an *early warning* model, not a detector.

Run from the project root:
    python ml/scripts/build_features.py --horizon 3
"""
import argparse
from pathlib import Path

import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
DATA = ML_DIR / "data"
RAIN_DIR = DATA / "raw" / "rainfall"
OUT_FILE = DATA / "processed" / "training_table.csv"

ROLLING_WINDOWS = [1, 3, 7, 14, 30]  # days of accumulated rainfall


def load_rainfall(rain_dir: Path = RAIN_DIR) -> pd.DataFrame:
    # Skip helper files like _bias_factors.csv; only per-village rainfall files.
    files = sorted(f for f in rain_dir.glob("*.csv") if not f.name.startswith("_"))
    if not files:
        raise SystemExit(f"No rainfall files in {rain_dir}. Run the matching fetch script first.")
    df = pd.concat((pd.read_csv(f, parse_dates=["date"]) for f in files), ignore_index=True)
    return df.sort_values(["village_id", "date"]).reset_index(drop=True)


def add_rain_features(df: pd.DataFrame) -> pd.DataFrame:
    # Missing days are rare in Open-Meteo; treat them as 0 mm but keep a flag.
    df["rain_missing"] = df["rain_mm"].isna().astype(int)
    df["rain_mm"] = df["rain_mm"].fillna(0.0)

    g = df.groupby("village_id")["rain_mm"]
    for w in ROLLING_WINDOWS:
        df[f"rain_{w}d"] = g.transform(lambda s, w=w: s.rolling(w, min_periods=1).sum())

    # Heaviest single day in the last week: intense bursts trigger landslides.
    df["rain_max_7d"] = g.transform(lambda s: s.rolling(7, min_periods=1).max())
    # Consecutive rainy days (> 2.5 mm) ending today: soil saturation proxy.
    rainy = df["rain_mm"] > 2.5
    streak_id = (~rainy).groupby(df["village_id"]).cumsum()
    df["wet_streak_days"] = rainy.groupby([df["village_id"], streak_id]).cumsum()

    # FORECAST features: rain over the NEXT k days (t+1 ... t+k).
    # In training these use the rain that actually fell, i.e. a "perfect forecast",
    # so results with them are an upper bound. In the live system they must come
    # from a real weather forecast (Open-Meteo forecast API), never from the future.
    # The training scripts only use them when asked (--forecast).
    for k in (1, 2, 3):
        df[f"fc_rain_{k}d"] = g.transform(
            lambda s, k=k: s[::-1].rolling(k, min_periods=1).sum()[::-1].shift(-1)
        ).fillna(0.0)

    df["month"] = df["date"].dt.month
    df["is_monsoon"] = df["month"].between(6, 9).astype(int)
    return df


def add_labels(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    events_file = DATA / "events.csv"
    events = pd.read_csv(events_file, parse_dates=["date"]) if events_file.exists() else None
    if events is None or events.empty:
        print("WARNING: events.csv is empty, so every label is 0. "
              "Add past flood/landslide records before training.")
        df["label"] = 0
        return df

    hit = events[["village_id", "date"]].drop_duplicates().assign(event_today=1)
    df = df.merge(hit, on=["village_id", "date"], how="left")
    df["event_today"] = df["event_today"].fillna(0).astype(int)

    # label = 1 if an event happens on any of the next `horizon` days (not today).
    future = df.groupby("village_id")["event_today"].transform(
        lambda s: s[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
    )
    df["label"] = future.fillna(0).astype(int)
    # Drop the last `horizon` days per village: their future isn't known yet.
    last_date = df.groupby("village_id")["date"].transform("max")
    df = df[df["date"] <= last_date - pd.Timedelta(days=horizon)]
    return df.drop(columns="event_today")


def add_static(df: pd.DataFrame) -> pd.DataFrame:
    villages = pd.read_csv(DATA / "villages.csv")[["village_id", "district", "lat", "lon"]]
    df = df.merge(villages, on="village_id", how="left")
    static_file = DATA / "village_static.csv"
    if static_file.exists():
        df = df.merge(pd.read_csv(static_file), on="village_id", how="left")
    else:
        print("note: no village_static.csv yet (slope, elevation, soil). See README, 'Next in Phase 1'.")
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=3,
                        help="predict events this many days ahead (default 3)")
    parser.add_argument("--rain-dir", default="rainfall",
                        help="folder under ml/data/raw/ with rainfall CSVs: "
                             "'rainfall' (Open-Meteo) or 'rainfall_imd' (IMD gauges)")
    args = parser.parse_args()

    df = load_rainfall(DATA / "raw" / args.rain_dir)
    print(f"rainfall source: ml/data/raw/{args.rain_dir}")
    df = add_rain_features(df)
    df = add_labels(df, args.horizon)
    df = add_static(df)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FILE, index=False)

    pos = int(df["label"].sum())
    print(f"saved {OUT_FILE.relative_to(ML_DIR.parent)}: {len(df):,} rows, "
          f"{df['village_id'].nunique()} villages, {pos} positive rows "
          f"({pos / max(len(df), 1):.3%})")


if __name__ == "__main__":
    main()
