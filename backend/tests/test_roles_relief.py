"""Roles (Gram Panchayat vs NGO vs villager), evacuation reports, SMS providers, DB upgrade."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import auth, config, database, sms
from backend.app.routers import alerts as alerts_router
from backend.tests.conftest import sign_in, villager_sign_in

SNAP = {"generated_at": "2026-08-01T09:00:00+05:30", "villages": [
    {"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada", "level": "HIGH",
     "past_3d_mm": 60.0, "forecast_3d_mm": 260.0, "reasons": ["test"], "daily_mm": []}]}
CFG = {"villages": [{"village_id": "V001", "name": "Ujire", "name_kn": "ಉಜಿರೆ", "district": "Dakshina Kannada"},
                    {"village_id": "V002", "name": "Belthangady", "name_kn": "ಬೆಳ್ತಂಗಡಿ", "district": "Dakshina Kannada"}],
       "calibrated_on": "test", "thresholds_mm": {}}
GP, NGO = "9876543210", "9123456780"


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "OTP_RESEND_S", 0)
    monkeypatch.setattr(config, "rule_config", lambda: CFG)
    monkeypatch.setattr(alerts_router, "_cached_or_fresh", lambda: SNAP)
    from backend.app.routers import risk as risk_router
    monkeypatch.setattr(risk_router, "_cached_or_fresh", lambda force=False: SNAP)
    from backend.app.main import app
    return app


def client(app):
    return TestClient(app)


# ---------- NGO vs Gram Panchayat ----------

def test_ngo_reads_but_cannot_approve(app_ctx):
    with client(app_ctx) as gp, client(app_ctx) as ngo:
        sign_in(gp, "Ujire GP", GP)
        me = sign_in(ngo, "Red Cross Belthangady", NGO, role="ngo")
        assert me["role"] == "ngo"
        a = gp.post("/alerts/generate").json()["alerts"][0]

        assert ngo.get("/alerts").json() == []                                # pending draft hidden from NGO
        assert ngo.get(f"/alerts/{a['id']}").status_code == 404
        assert ngo.post(f"/alerts/{a['id']}/approve", json={}).status_code == 403
        assert ngo.post("/alerts/generate").status_code == 403
        assert ngo.post("/system/scheduler/run-now").status_code == 403
        assert ngo.get("/risk").status_code == 200                            # can see risk to prepare

        gp.post(f"/alerts/{a['id']}/approve", json={})
        assert [x["id"] for x in ngo.get("/alerts?status=pending").json()] == [a["id"]]   # forced to approved


# ---------- villagers ----------

def test_villager_sign_in_needs_a_known_village(app_ctx):
    with client(app_ctx) as v:
        code = v.post("/public/auth/request-code", json={"phone": "9000000001"}).json()["demo_code"]
        r = v.post("/public/auth/verify", json={"phone": "9000000001", "code": code, "village_id": "V999"})
        assert r.status_code == 422


def test_report_flow_and_validation(app_ctx):
    with client(app_ctx) as v:
        assert v.post("/public/report", json={"village_id": "V001", "at_shelter": 1}).status_code == 401
        villager_sign_in(v)
        assert v.post("/public/report", json={"village_id": "V001"}).status_code == 422          # nobody reported
        assert v.post("/public/report", json={"village_id": "V001", "at_home": 99}).status_code == 422  # > 50
        assert v.post("/public/report", json={"village_id": "V001", "at_home": 1, "needs": ["pizza"]}).status_code == 422
        r = v.post("/public/report", json={"village_id": "V001", "at_shelter": 3, "unknown": 1,
                                           "needs": ["rescue", "water", "water"]}).json()
        assert r["report"]["needs"] == ["rescue", "water"]
        # A new report replaces the old one (one row per family).
        v.post("/public/report", json={"village_id": "V001", "at_shelter": 4})
        assert v.get("/public/me").json()["report"]["at_shelter"] == 4
        # A villager session doesn't open the staff dashboard.
        assert v.get("/alerts").status_code == 401 and v.get("/relief/summary").status_code == 401


def test_relief_summary_and_family_list_permissions(app_ctx):
    with client(app_ctx) as v1, client(app_ctx) as v2, client(app_ctx) as gp, client(app_ctx) as ngo:
        villager_sign_in(v1, "9000000001", "V001")
        v1.post("/public/report", json={"village_id": "V001", "at_shelter": 3, "unknown": 1, "needs": ["rescue"]})
        villager_sign_in(v2, "9000000002", "V001")
        v2.post("/public/report", json={"village_id": "V001", "with_relatives": 2, "needs": ["food"]})
        sign_in(gp, "Ujire GP", GP)
        sign_in(ngo, "Red Cross", NGO, role="ngo")

        s = ngo.get("/relief/summary").json()
        ujire = s["villages"][0]
        assert ujire["village_id"] == "V001"                      # rescue requests sort first
        assert (ujire["families"], ujire["at_shelter"], ujire["with_relatives"], ujire["unknown"]) == (2, 3, 2, 1)
        assert ujire["rescue_requests"] == 1 and ujire["needs"] == {"rescue": 1, "food": 1}
        assert "9000000001" not in str(s)                          # no phone numbers for NGOs
        assert s["totals"]["families"] == 2

        assert ngo.get("/relief/reports/V001").status_code == 403
        fam = gp.get("/relief/reports/V001").json()["families"]
        assert fam[0]["phone"] == "+919000000001" and fam[0]["needs"] == ["rescue"]   # rescue first, callable number


# ---------- SMS providers ----------

def test_twilio_provider(app_ctx, monkeypatch):
    sent, checked = [], []
    monkeypatch.setattr(config, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(sms, "twilio_start", lambda phone: sent.append(phone))
    monkeypatch.setattr(sms, "twilio_check", lambda phone, code: checked.append(code) or code == "424242")
    with client(app_ctx) as c:
        auth.add_official(GP, "Ujire GP")
        r = c.post("/auth/request-code", json={"phone": GP}).json()
        assert sent == ["+919876543210"] and "demo_code" not in r and r["sent_by"] == "twilio"
        assert c.post("/auth/verify", json={"phone": GP, "code": "111111"}).status_code == 401
        assert c.post("/auth/verify", json={"phone": GP, "code": "424242"}).status_code == 200
        assert checked == ["111111", "424242"]


def test_fast2sms_provider_and_failure(app_ctx, monkeypatch):
    sent = {}
    monkeypatch.setattr(config, "SMS_PROVIDER", "fast2sms")
    monkeypatch.setattr(sms, "fast2sms_send", lambda phone, code: sent.update(phone=phone, code=code))
    with client(app_ctx) as c:
        r = c.post("/public/auth/request-code", json={"phone": "9000000001"}).json()
        assert "demo_code" not in r and sent["phone"] == "+919000000001"
        ok = c.post("/public/auth/verify", json={"phone": "9000000001", "code": sent["code"], "village_id": "V001"})
        assert ok.status_code == 200

        def broken(phone, code):
            raise sms.SMSError("Fast2SMS refused: insufficient balance")
        monkeypatch.setattr(sms, "fast2sms_send", broken)
        r = c.post("/public/auth/request-code", json={"phone": "9000000002"})
        assert r.status_code == 502 and "insufficient balance" in r.json()["detail"]


def test_missing_twilio_settings_explained(monkeypatch):
    monkeypatch.setattr(config, "TWILIO_ACCOUNT_SID", "")
    with pytest.raises(sms.SMSError, match="TWILIO_ACCOUNT_SID"):
        sms.twilio_start("+919876543210")


# ---------- upgrading an older database ----------

def test_old_database_is_upgraded(tmp_path, monkeypatch):
    db = tmp_path / "alerts.db"
    old = sqlite3.connect(db)
    old.executescript("""
        CREATE TABLE officials (phone TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO officials VALUES ('+919876543210', 'Ujire GP', '2026-10-24');
        CREATE TABLE otp_codes (phone TEXT PRIMARY KEY, code_hash TEXT, sent_at TEXT, expires_at TEXT, attempts INTEGER);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, phone TEXT, created_at TEXT, expires_at TEXT);""")
    old.close()
    monkeypatch.setattr(config, "ALERTS_DB", db)
    database.init_db()
    assert auth.get_official("+919876543210")["role"] == "gp"          # existing official kept, now a GP
    with database.connect() as c:
        assert "purpose" in database._columns(c, "otp_codes") and "kind" in database._columns(c, "sessions")
