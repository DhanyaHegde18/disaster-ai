"""Sign-in: only registered officials, codes expire and lock, sessions guard the dashboard API."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import auth, config, database
from backend.app.routers import alerts as alerts_router
from backend.tests.conftest import TEST_PHONE, sign_in

SNAP = {"generated_at": "2026-08-01T09:00:00+05:30", "villages": [
    {"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada", "level": "HIGH",
     "past_3d_mm": 60.0, "forecast_3d_mm": 260.0, "reasons": ["test"], "daily_mm": []}]}
CFG = {"villages": [{"village_id": "V001", "name": "Ujire", "name_kn": "ಉಜಿರೆ", "district": "Dakshina Kannada"}],
       "calibrated_on": "test", "thresholds_mm": {}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "OTP_RESEND_S", 0)
    monkeypatch.setattr(config, "rule_config", lambda: CFG)
    monkeypatch.setattr(alerts_router, "_cached_or_fresh", lambda: SNAP)
    from backend.app.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("raw", ["9876543210", "09876543210", "+91 98765 43210", "919876543210"])
def test_phone_formats(raw):
    assert auth.normalize_phone(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["12345", "5876543210", "abcdefghij", ""])
def test_bad_phones(raw):
    with pytest.raises(auth.AuthError):
        auth.normalize_phone(raw)


def test_protected_endpoints_need_sign_in(client):
    for method, path in [("get", "/risk"), ("get", "/alerts"), ("post", "/alerts/generate"),
                         ("post", "/alerts/1/approve"), ("post", "/system/scheduler/run-now"), ("get", "/auth/me")]:
        assert getattr(client, method)(path).status_code == 401, path
    # Villagers and health checks stay open.
    assert client.get("/public/villages").status_code == 200
    assert client.get("/health").status_code == 200


def test_unregistered_number_cannot_get_a_code(client):
    r = client.post("/auth/request-code", json={"phone": "9123456789"})
    assert r.status_code == 403 and "not registered" in r.json()["detail"]


def test_full_sign_in_and_out(client):
    me = sign_in(client, name="Ujire GP secretary")
    assert me["name"] == "Ujire GP secretary" and me["phone"].endswith("3210")
    assert "9876543210" not in me["phone"]                       # number is masked
    assert client.get("/auth/me").status_code == 200
    assert client.get("/alerts").status_code == 200
    client.post("/auth/logout")
    assert client.get("/alerts").status_code == 401


def test_approval_records_the_signed_in_official(client):
    sign_in(client, name="Ujire GP secretary")
    a = client.post("/alerts/generate").json()["alerts"][0]
    # Even if a request claims another name, the session decides who approved.
    r = client.post(f"/alerts/{a['id']}/approve", json={"reviewed_by": "Someone Else"}).json()
    assert r["reviewed_by"] == "Ujire GP secretary"


def test_reject_needs_a_note(client):
    sign_in(client)
    a = client.post("/alerts/generate").json()["alerts"][0]
    assert client.post(f"/alerts/{a['id']}/reject", json={}).status_code == 422
    assert client.post(f"/alerts/{a['id']}/reject", json={"note": "rain stopped"}).json()["status"] == "rejected"


def test_wrong_codes_lock_after_max_attempts(client):
    auth.add_official(TEST_PHONE, "Ujire GP")
    code = client.post("/auth/request-code", json={"phone": TEST_PHONE}).json()["demo_code"]
    wrong = "000000" if code != "000000" else "111111"
    for i in range(config.OTP_MAX_ATTEMPTS):
        r = client.post("/auth/verify", json={"phone": TEST_PHONE, "code": wrong})
        assert r.status_code == 401
    # Now even the right code is refused until a new one is requested.
    r = client.post("/auth/verify", json={"phone": TEST_PHONE, "code": code})
    assert r.status_code == 429


def test_code_works_only_once(client):
    auth.add_official(TEST_PHONE, "Ujire GP")
    code = client.post("/auth/request-code", json={"phone": TEST_PHONE}).json()["demo_code"]
    assert client.post("/auth/verify", json={"phone": TEST_PHONE, "code": code}).status_code == 200
    assert client.post("/auth/verify", json={"phone": TEST_PHONE, "code": code}).status_code == 401


def test_expired_code_refused(client):
    auth.add_official(TEST_PHONE, "Ujire GP")
    code = client.post("/auth/request-code", json={"phone": TEST_PHONE}).json()["demo_code"]
    past = (datetime.now() - timedelta(minutes=1)).astimezone().isoformat(timespec="seconds")
    with database.connect() as c:
        c.execute("UPDATE otp_codes SET expires_at = ?", (past,))
    r = client.post("/auth/verify", json={"phone": TEST_PHONE, "code": code})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_resend_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(config, "OTP_RESEND_S", 30)
    auth.add_official(TEST_PHONE, "Ujire GP")
    assert client.post("/auth/request-code", json={"phone": TEST_PHONE}).status_code == 200
    assert client.post("/auth/request-code", json={"phone": TEST_PHONE}).status_code == 429


def test_removing_an_official_signs_them_out(client):
    sign_in(client)
    auth.remove_official(TEST_PHONE)
    assert client.get("/alerts").status_code == 401


def test_session_cookie_is_httponly_and_strict(client):
    auth.add_official(TEST_PHONE, "Ujire GP")
    code = client.post("/auth/request-code", json={"phone": TEST_PHONE}).json()["demo_code"]
    r = client.post("/auth/verify", json={"phone": TEST_PHONE, "code": code})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
