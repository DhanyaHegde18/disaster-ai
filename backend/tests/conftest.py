"""
Shared test setup: every test runs in a small made-up Karnataka with its own empty database,
fake rain (no network), demo SMS codes and no phone pushes.

  Dakshina Kannada   Belthangady taluk: Ujre, Dharmasthala, Laila    Sullia taluk: Subramanya
  Udupi              Udupi taluk: Kukkehalli
Rain-grid squares: 13.00_75.25 (Ujre, Dharmasthala), 12.75_75.25 (Laila), 12.75_75.50 (Subramanya),
13.25_74.75 (Kukkehalli). Thresholds everywhere: MEDIUM 100 mm, HIGH 150 mm over 3 days.
Use `world.rain(cell, past, future)` to make a square wet.
"""
import csv
import datetime as dt
import json

import pytest

from backend.app import auth, config

TEST_PHONE = "9876543210"
BELTHANGADY, SULLIA, UDUPI = "dakshina-kannada:belthangady", "dakshina-kannada:sullia", "udupi:udupi"
VILLAGES = [
    # id, name, district, taluk, taluk_id, lat, lon, population, cell
    ("KA001", "Ujre", "Dakshina Kannada", "Belthangady", BELTHANGADY, 12.99, 75.33, 12474, "13.00_75.25"),
    ("KA002", "Dharmasthala", "Dakshina Kannada", "Belthangady", BELTHANGADY, 12.95, 75.30, 9258, "13.00_75.25"),
    ("KA003", "Laila", "Dakshina Kannada", "Belthangady", BELTHANGADY, 12.80, 75.20, 6000, "12.75_75.25"),
    ("KA004", "Subramanya", "Dakshina Kannada", "Sullia", SULLIA, 12.67, 75.62, 3447, "12.75_75.50"),
    ("KA005", "Kukkehalli", "Udupi", "Udupi", UDUPI, 13.37, 74.84, 2968, "13.25_74.75"),
]
CELLS = sorted({v[8] for v in VILLAGES})
T = {"medium": 100.0, "high": 150.0}
GRID = {"demo": False, "calibrated_on": "test", "source": "test grid",
        "cells": {c: {"lat": float(c.split("_")[0]), "lon": float(c.split("_")[1]), "villages": 1,
                      "past_3d": dict(T), "forecast_3d": dict(T), "bias": {}} for c in CELLS}}


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self._rain = {}
        self.asked_past_days = None

    def rain(self, cell: str, past: float = 0.0, future: float = 0.0, soaked: float = 0.0) -> None:
        """Set a square's rain: `past` over day -2..today, `future` over day +1..+3,
        `soaked` spread over the 12 days before that (for the landslide model)."""
        self._rain[cell] = (past, future, soaked)
        self.asked_past_days = None

    def daily(self, points: dict, past_days: int = 2) -> dict:
        self.asked_past_days = past_days
        today = dt.date.today()
        out = {}
        for k in points:
            past, fut, soaked = self._rain.get(k, (3.0, 3.0, 0.0))
            early = past_days - 2
            vals = [soaked / max(early, 1)] * early + [past / 3] * 3 + [fut / 3] * 3
            days = [today + dt.timedelta(days=i - past_days) for i in range(len(vals))]
            out[k] = list(zip(days, vals))
        return out


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    vcsv = tmp_path / "villages.csv"
    with open(vcsv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["village_id", "name", "district", "taluk", "taluk_id", "census_taluk", "lat", "lon", "population", "cell_id"])
        for v in VILLAGES:
            w.writerow([*v[:5], v[3], *v[5:]])
    areas_json = tmp_path / "areas.json"
    taluks = {}
    for v in VILLAGES:
        t = taluks.setdefault(v[4], {"taluk_id": v[4], "name": v[3], "census_name": v[3], "villages": 0,
                                     "cells": set(), "district": v[2]})
        t["villages"] += 1
        t["cells"].add(v[8])
    districts = []
    for d, kn in (("Dakshina Kannada", "ದಕ್ಷಿಣ ಕನ್ನಡ"), ("Udupi", "ಉಡುಪಿ")):
        districts.append({"name": d, "name_kn": kn, "taluks": [
            {k: (sorted(t[k]) if k == "cells" else t[k]) for k in ("taluk_id", "name", "census_name", "villages", "cells")}
            for t in taluks.values() if t["district"] == d]})
    areas_json.write_text(json.dumps({"districts": districts}, ensure_ascii=False), encoding="utf-8")

    w = World(tmp_path)
    monkeypatch.setattr(config, "VILLAGES_CSV", vcsv)
    monkeypatch.setattr(config, "AREAS_JSON", areas_json)
    monkeypatch.setattr(config, "VILLAGE_NAMES_KN_CSV", tmp_path / "village_names_kn.csv")
    monkeypatch.setattr(config, "TALUK_NAMES_KN_CSV", tmp_path / "taluk_names_kn.csv")
    monkeypatch.setattr(config, "NAME_KN_FIXES_CSV", tmp_path / "name_kn_fixes.csv")
    monkeypatch.setattr(config, "RIVER_CONFIG", tmp_path / "river_config.json")   # no rivers unless a test adds them
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "LATEST_RISK_FILE", tmp_path / "latest_risk.json")
    monkeypatch.setattr(config, "SHELTERS_CSV", tmp_path / "shelters.csv")
    monkeypatch.setattr(config, "SHELTER_CANDIDATES_CSV", tmp_path / "shelter_candidates.csv")
    monkeypatch.setattr(config, "grid_config", lambda: GRID)
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "OTP_RESEND_S", 0)
    monkeypatch.setattr(config, "SMS_PROVIDER", "demo")      # tests never send real SMS, whatever .env says
    monkeypatch.setattr(config, "OTP_DEMO_MODE", True)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "")         # ...and never push to real phones
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", "")
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(config, "STATE_REPO", "")             # never back up test databases to a real repository
    monkeypatch.setattr(config, "HF_TOKEN", "")
    monkeypatch.setattr(config, "OFFICIALS", "")
    monkeypatch.setattr(config, "OPEN_SIGNIN", "off")      # the test client talks plain http, even if .env says https
    from backend.app.jobs import score_grid
    monkeypatch.setattr(score_grid, "fetch_daily_rain", w.daily)
    from backend.app.services import landslide                 # no landslide model unless a test trains one
    monkeypatch.setattr(landslide, "MODEL_FILE", tmp_path / "landslide_model.joblib")
    monkeypatch.setattr(landslide, "META_FILE", tmp_path / "landslide_model.json")
    from backend.app.routers import risk as risk_router            # forget forecast failures of other tests
    monkeypatch.setattr(risk_router, "_failed", {"at": None, "why": ""})
    from backend.app import database
    database.init_db()
    return w


def app_client():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    return TestClient(app)


def sign_in(client, name="Ujire GP", phone=TEST_PHONE, role="gp", taluk_id=BELTHANGADY, district=None):
    """Register a staff member and sign in through the real OTP flow (demo mode returns the code)."""
    auth.add_official(phone, name, role, taluk_id=taluk_id, district=district)
    code = client.post("/auth/request-code", json={"phone": phone}).json()["demo_code"]
    r = client.post("/auth/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def villager_sign_in(client, phone="9000000001", village_id="KA001"):
    code = client.post("/public/auth/request-code", json={"phone": phone}).json()["demo_code"]
    r = client.post("/public/auth/verify", json={"phone": phone, "code": code, "village_id": village_id})
    assert r.status_code == 200, r.text
    return r.json()
