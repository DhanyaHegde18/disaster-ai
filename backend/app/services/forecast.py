"""
Live rainfall for every rain-grid square from Open-Meteo's free forecast API (no key).

About 310 squares, sent FORECAST_BATCH at a time with a short pause between requests
(each location counts as one call against the free 10,000-a-day limit; every 3 hours that's
about 2,500 a day). For each square we get 6 daily values:
  day -2, day -1, today, day +1, day +2, day +3      (past_days=2 + forecast_days=4)
"""
import time
from datetime import date

import requests

from .. import config


def _get(params: dict) -> list:
    last_err = None
    for attempt in range(1, config.RETRIES + 1):
        try:
            resp = requests.get(config.FORECAST_URL, params=params, timeout=config.REQUEST_TIMEOUT_S)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code} server busy")
            resp.raise_for_status()
            payload = resp.json()
            return payload if isinstance(payload, list) else [payload]   # one location -> a dict
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as err:
            last_err = err
            if attempt < config.RETRIES:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Open-Meteo forecast unavailable after {config.RETRIES} tries: {last_err}")


def fetch_daily_rain(points: dict[str, tuple[float, float]]) -> dict[str, list[tuple[date, float]]]:
    """points: {id: (lat, lon)} -> {id: [(day, mm), ...]}"""
    ids = list(points)
    out = {}
    for i in range(0, len(ids), config.FORECAST_BATCH):
        batch = ids[i:i + config.FORECAST_BATCH]
        params = {
            "latitude": ",".join(str(points[k][0]) for k in batch),
            "longitude": ",".join(str(points[k][1]) for k in batch),
            "daily": "precipitation_sum",
            "past_days": 2,
            "forecast_days": 4,
            "timezone": config.TIMEZONE,
        }
        for k, r in zip(batch, _get(params)):
            days = [date.fromisoformat(d) for d in r["daily"]["time"]]
            rain = [float(x) if x is not None else 0.0 for x in r["daily"]["precipitation_sum"]]
            out[k] = list(zip(days, rain))
        if i + config.FORECAST_BATCH < len(ids):
            time.sleep(config.FORECAST_PAUSE_S)
    return out
