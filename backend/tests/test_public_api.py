"""Villagers must only ever see approved, real alerts."""
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.routers import alerts as alerts_router
from backend.tests.conftest import sign_in

RISK = {"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada", "level": "HIGH",
        "past_3d_mm": 60.0, "forecast_3d_mm": 260.0, "reasons": ["test"], "daily_mm": []}
SNAP = {"generated_at": "2026-08-01T09:00:00+05:30", "villages": [RISK]}
CFG = {"villages": [{"village_id": "V001", "name": "Ujire", "name_kn": "ಉಜಿರೆ", "district": "Dakshina Kannada"}],
       "calibrated_on": "test", "thresholds_mm": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "rule_config", lambda: CFG)
    monkeypatch.setattr(alerts_router, "_cached_or_fresh", lambda: SNAP)
    from backend.app.main import app
    with TestClient(app) as c:
        sign_in(c, name="Ujire GP")
        yield c


def draft(c, simulate=False):
    if simulate:
        return c.post("/alerts/draft/V001?simulate_high=true").json()
    return c.post("/alerts/generate").json()["alerts"][0]


def test_pending_alerts_are_not_public(client):
    draft(client)
    s = client.get("/public/status/V001").json()
    assert s["active"] == [] and s["recent"] == []


def test_approved_alert_is_public_and_active(client):
    a = draft(client)
    client.post(f"/alerts/{a['id']}/approve", json={"reviewed_by": "Ujire GP"})
    s = client.get("/public/status/v001").json()
    assert [x["id"] for x in s["active"]] == [a["id"]]
    assert s["active"][0]["approved_by"] == "Ujire GP" and s["active"][0]["test"] is False
    assert "ಉಜಿರೆ" in s["active"][0]["message_kn"]


def test_rejected_alerts_are_not_public(client):
    a = draft(client)
    client.post(f"/alerts/{a['id']}/reject", json={"reviewed_by": "Ujire GP", "note": "wrong"})
    assert client.get("/public/status/V001").json()["active"] == []


def test_simulated_only_in_demo_mode(client):
    a = draft(client, simulate=True)
    client.post(f"/alerts/{a['id']}/approve", json={"reviewed_by": "Ujire GP"})
    assert client.get("/public/status/V001").json()["active"] == []
    demo = client.get("/public/status/V001?demo=true").json()["active"]
    assert len(demo) == 1 and demo[0]["test"] is True


def test_villages_and_unknown(client):
    assert client.get("/public/villages").json()[0]["name_kn"] == "ಉಜಿರೆ"
    assert client.get("/public/status/V999").status_code == 404
