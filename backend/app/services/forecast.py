"""
Live rainfall for every village from Open-Meteo's free forecast API (no key).

One request covers all villages. For each village we get 6 daily values:
  day -2, day -1, today, day +1, day +2, day +3
(past_days=2 + forecast_days=4). "Today" is partly observed, partly forecast.
"""
import time
from datetime import date

import requests

from .. import config


def fetch_daily_rain(villages: list[dict]) -> dict[str, list[tuple[date, float]]]:
    params = {
        "latitude": ",".join(str(v["lat"]) for v in villages),
        "longitude": ",".join(str(v["lon"]) for v in villages),
        "daily": "precipitation_sum",
        "past_days": 2,
        "forecast_days": 4,
        "timezone": config.TIMEZONE,
    }
    last_err = None
    for attempt in range(1, config.RETRIES + 1):
        try:
            resp = requests.get(config.FORECAST_URL, params=params, timeout=config.REQUEST_TIMEOUT_S)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code} server busy")
            resp.raise_for_status()
            break
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as err:
            last_err = err
            if attempt < config.RETRIES:
                time.sleep(5 * attempt)
    else:
        raise RuntimeError(f"Open-Meteo forecast unavailable after {config.RETRIES} tries: {last_err}")

    payload = resp.json()
    results = payload if isinstance(payload, list) else [payload]  # one village -> a dict, not a list
    out = {}
    for v, r in zip(villages, results):
        days = [date.fromisoformat(d) for d in r["daily"]["time"]]
        rain = [float(x) if x is not None else 0.0 for x in r["daily"]["precipitation_sum"]]
        out[v["village_id"]] = list(zip(days, rain))
    return out
