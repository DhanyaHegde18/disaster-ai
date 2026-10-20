"""
Phase 1 (upgrade): daily rainfall from IMD's gauge-based gridded data.

Why: Open-Meteo's model-based rainfall badly underestimates Western Ghats
downpours (e.g. ~41 mm at Ujire on 1 Aug 2026 vs 348 mm measured at a gauge
in Mundaje). IMD's 0.25 deg grid is built from thousands of real rain gauges,
so extreme local rain shows up much better.

Source : India Meteorological Department gridded rainfall, via the `imdlib` package
         - archive: complete years (published with a delay)
         - real-time: recent days, filled in after the archive ends
Input  : ml/data/villages.csv
Output : ml/data/raw/rainfall_imd/<village_id>.csv   (village_id, date, rain_mm)
         IMD .grd downloads are cached in ml/data/raw/imd_grd/

Run from the project root:
    pip install imdlib
    python ml/scripts/fetch_rainfall_imd.py --start-year 2015 --end 2026-09-30
Then build features from it:
    python ml/scripts/build_features.py --rain-dir rainfall_imd
"""
import argparse
from datetime import date
from pathlib import Path

import imdlib as imd
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
VILLAGES_CSV = ML_DIR / "data" / "villages.csv"
GRD_DIR = ML_DIR / "data" / "raw" / "imd_grd"
OUT_DIR = ML_DIR / "data" / "raw" / "rainfall_imd"


def to_village_series(ds, villages: pd.DataFrame) -> dict[str, pd.Series]:
    """Daily rain at the grid cell nearest each village."""
    var = list(ds.data_vars)[0]
    out = {}
    for v in villages.itertuples(index=False):
        point = ds[var].sel(lat=v.lat, lon=v.lon, method="nearest")
        out[v.village_id] = point.to_series()
    return out


def download_archive(start_year: int, end_year: int):
    """Complete years from the archive. Steps back a year if the latest isn't published."""
    for last in range(end_year, start_year - 1, -1):
        try:
            print(f"archive: requesting {start_year}-{last} ...")
            data = imd.get_data("rain", start_year, last, fn_format="yearwise",
                                file_dir=str(GRD_DIR))
            return data.get_xarray(), last
        except Exception as err:  # imdlib raises when a year isn't published yet
            print(f"  {last} not available ({err}); trying one year earlier")
    raise SystemExit("Could not download any archive years from IMD.")


def download_realtime(start: str, end: str):
    """Recent days from IMD's real-time feed, one month at a time.

    A month that isn't published is skipped; for the latest month we step the
    end date back a few days at a time, since the newest days lag behind."""
    parts = []
    month_start = pd.Timestamp(start)
    end_day = pd.Timestamp(end)
    while month_start <= end_day:
        month_end = min(month_start + pd.offsets.MonthEnd(0), end_day)
        last = month_end
        while last >= month_start:
            try:
                data = imd.get_real_data("rain", str(month_start.date()), str(last.date()),
                                         file_dir=str(GRD_DIR))
                parts.append(data.get_xarray())
                print(f"real-time: got {month_start.date()} to {last.date()}")
                break
            except Exception as err:
                if month_end < end_day:  # an older month: don't retry day by day
                    print(f"real-time: {month_start:%Y-%m} not available ({err}); skipping")
                    break
                last -= pd.Timedelta(days=3)
        month_start = month_end + pd.Timedelta(days=1)
    if not parts:
        print("  no real-time data available for that range")
        return None
    import xarray as xr
    return xr.concat(parts, dim="time")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end", default=str(date.today()), help="last day wanted, YYYY-MM-DD")
    args = parser.parse_args()

    villages = pd.read_csv(VILLAGES_CSV)
    GRD_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(args.end)

    archive_ds, last_year = download_archive(args.start_year, end.year)
    series = to_village_series(archive_ds, villages)

    rt_start = pd.Timestamp(year=last_year + 1, month=1, day=1)
    if rt_start <= end:
        rt_ds = download_realtime(str(rt_start.date()), str(end.date()))
        if rt_ds is not None:
            rt_series = to_village_series(rt_ds, villages)
            series = {k: pd.concat([series[k], rt_series[k]]) for k in series}

    for v in villages.itertuples(index=False):
        s = series[v.village_id]
        s = s[~s.index.duplicated(keep="first")].sort_index()
        # Every calendar day gets a row; unpublished days become NaN (flagged later
        # as rain_missing) instead of silently disappearing and breaking rolling sums.
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
        df = pd.DataFrame({"village_id": v.village_id,
                           "date": pd.to_datetime(s.index).strftime("%Y-%m-%d"),
                           "rain_mm": s.round(1).to_numpy()})
        df.to_csv(OUT_DIR / f"{v.village_id}.csv", index=False)
        print(f"saved  {v.village_id} ({v.name}): {len(df)} days "
              f"({df['date'].iloc[0]} to {df['date'].iloc[-1]}), "
              f"{df['rain_mm'].isna().sum()} missing")


if __name__ == "__main__":
    main()
