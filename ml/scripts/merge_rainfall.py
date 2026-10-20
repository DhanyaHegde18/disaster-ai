"""
Phase 1 (upgrade): combine IMD and Open-Meteo rainfall into one gap-free series.

Why
  * IMD (rain-gauge based) is the more realistic source, but its real-time feed
    for recent months is full of gaps.
  * Open-Meteo is complete but reads too low in the Western Ghats
    (e.g. Ujire, Aug 2018: IMD 1,488 mm vs Open-Meteo 670 mm).

How
  1. Use IMD wherever it has a value.
  2. Fill IMD's gaps with Open-Meteo, after BIAS CORRECTION:
     for each village and calendar month, compare the two sources over the
     years where both exist and compute  factor = IMD total / Open-Meteo total.
     A gap day in August is then  Open-Meteo rain x that village's August factor.
     Factors are clipped to 0.5 to 3.0 so one odd month can't explode them.
  3. Record where each value came from in `rain_source` ("imd" or "openmeteo_corrected"),
     so you can always check how much of a period is real gauge data.

Input : ml/data/raw/rainfall_imd/*.csv   (fetch_rainfall_imd.py)
        ml/data/raw/rainfall/*.csv       (fetch_rainfall.py)
Output: ml/data/raw/rainfall_merged/<village_id>.csv
        (village_id, date, rain_mm, rain_source)
        ml/data/raw/rainfall_merged/_bias_factors.csv   (the factors, to inspect)

Run from the project root:
    python ml/scripts/merge_rainfall.py
    python ml/scripts/build_features.py --rain-dir rainfall_merged
"""
from pathlib import Path

import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
RAW = ML_DIR / "data" / "raw"
IMD_DIR = RAW / "rainfall_imd"
OM_DIR = RAW / "rainfall"
OUT_DIR = RAW / "rainfall_merged"

FACTOR_MIN, FACTOR_MAX = 0.5, 3.0
MIN_OM_TOTAL_MM = 20.0  # months drier than this give unreliable ratios -> factor 1.0


def load(folder: Path) -> pd.DataFrame:
    files = sorted(folder.glob("V*.csv"))
    if not files:
        raise SystemExit(f"No files in {folder}. Run the matching fetch script first.")
    return pd.concat((pd.read_csv(f, parse_dates=["date"]) for f in files), ignore_index=True)


def main() -> None:
    imd = load(IMD_DIR).rename(columns={"rain_mm": "imd"})
    om = load(OM_DIR).rename(columns={"rain_mm": "om"})
    df = om.merge(imd, on=["village_id", "date"], how="left")  # Open-Meteo has every day
    df["month"] = df["date"].dt.month

    # Bias factors from days where BOTH sources have a value.
    both = df.dropna(subset=["imd", "om"])
    totals = both.groupby(["village_id", "month"])[["imd", "om"]].sum()
    totals["factor"] = (totals["imd"] / totals["om"]).clip(FACTOR_MIN, FACTOR_MAX)
    totals.loc[totals["om"] < MIN_OM_TOTAL_MM, "factor"] = 1.0
    df = df.merge(totals["factor"].reset_index(), on=["village_id", "month"], how="left")
    df["factor"] = df["factor"].fillna(1.0)

    use_imd = df["imd"].notna()
    df["rain_mm"] = df["imd"].where(use_imd, (df["om"] * df["factor"]).round(1))
    df["rain_source"] = use_imd.map({True: "imd", False: "openmeteo_corrected"})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    totals.round(2).reset_index().to_csv(OUT_DIR / "_bias_factors.csv", index=False)
    for vid, g in df.groupby("village_id"):
        g[["village_id", "date", "rain_mm", "rain_source"]].assign(
            date=g["date"].dt.strftime("%Y-%m-%d")
        ).to_csv(OUT_DIR / f"{vid}.csv", index=False)
        share = (g["rain_source"] == "imd").mean()
        print(f"saved  {vid}: {len(g)} days, {share:.0%} from IMD, "
              f"{(~(g['rain_source'] == 'imd')).sum()} filled from corrected Open-Meteo")

    monsoon = totals.reset_index()
    monsoon = monsoon[monsoon["month"].between(6, 9)]
    print("\nMonsoon bias factors (IMD / Open-Meteo), per village:")
    print(monsoon.pivot(index="village_id", columns="month", values="factor").round(2).to_string())


if __name__ == "__main__":
    main()
