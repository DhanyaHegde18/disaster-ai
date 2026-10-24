"""End-to-end tests of the alert endpoints with a temporary database and no network."""
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.routers import alerts as alerts_router
from backend.tests.conftest import sign_in

SNAPSHOT = {
    "generated_at": "2026-08-01T09:00:00+05:30",
    "villages": [
        {"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada", "level": "HIGH",
         "past_3d_mm": 60.0, "forecast_3d_mm": 260.0, "reasons": ["test"], "daily_mm": []},
        {"village_id": "V004", "name": "Madikeri", "district": "Kodagu", "level": "LOW",
         "past_3d_mm": 5.0, "forecast_3d_mm": 10.0, "reasons": ["test"], "daily_mm": []},
    ],
}
CFG = {"villages": [{"village_id": "V001", "name": "Ujire", "name_kn": "ಉಜಿರೆ"},
                    {"village_id": "V004", "name": "Madikeri", "name_kn": "ಮಡಿಕೇರಿ"}],
       "calibrated_on": "test", "thresholds_mm": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)   # no background network calls in tests
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")          # template only, no network
    monkeypatch.setattr(config, "rule_config", lambda: CFG)
    monkeypatch.setattr(alerts_router, "_cached_or_fresh", lambda: SNAPSHOT)
    from backend.app.main import app
    with TestClient(app) as c:
        sign_in(c, name="Ujire GP")
        yield c


def test_generate_only_high_and_only_once_a_day(client):
    r = client.post("/alerts/generate").json()
    assert r["created"] == 1 and r["alerts"][0]["village_id"] == "V001"
    assert client.post("/alerts/generate").json()["created"] == 0   # already has one today


def test_review_flow(client):
    a = client.post("/alerts/generate").json()["alerts"][0]
    assert a["status"] == "pending" and a["source"] == "template"
    assert "ಉಜಿರೆ" in a["message_kn"]

    e = client.put(f"/alerts/{a['id']}", json={"message_en": "Edited text for Ujire. Emergency 112."}).json()
    assert e["edited"] is True and e["message_en"].startswith("Edited")

    ok = client.post(f"/alerts/{a['id']}/approve", json={"reviewed_by": "Ujire GP"}).json()
    assert ok["status"] == "approved" and ok["reviewed_by"] == "Ujire GP"

    # No editing or re-reviewing after a decision.
    assert client.put(f"/alerts/{a['id']}", json={"message_en": "x"}).status_code == 409
    assert client.post(f"/alerts/{a['id']}/reject", json={"note": "late"}).status_code == 409
    assert [x["id"] for x in client.get("/alerts?status=approved").json()] == [a["id"]]


def test_low_village_needs_simulation(client):
    assert client.post("/alerts/draft/V004").status_code == 409
    s = client.post("/alerts/draft/V004?simulate_high=true").json()
    assert s["simulated"] is True and s["level"] == "HIGH"
    # A simulated alert doesn't block a real one later.
    assert client.post("/alerts/generate").json()["created"] == 1


def test_unknown_ids(client):
    assert client.get("/alerts/999").status_code == 404
    assert client.post("/alerts/draft/V999").status_code == 404
    assert client.post("/alerts/1/approve", json={"reviewed_by": "x"}).status_code in (404, 422)
