"""Shared test helpers."""
import pytest

from backend.app import auth, config

TEST_PHONE = "9876543210"


@pytest.fixture(autouse=True)
def demo_sms(monkeypatch):
    """Tests never send real SMS, whatever .env says."""
    monkeypatch.setattr(config, "SMS_PROVIDER", "demo")
    monkeypatch.setattr(config, "OTP_DEMO_MODE", True)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "")      # ...and never push to real phones
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", "")


def sign_in(client, name="Ujire GP", phone=TEST_PHONE, role="gp"):
    """Register a staff member and sign in through the real OTP flow (demo mode returns the code)."""
    auth.add_official(phone, name, role)
    code = client.post("/auth/request-code", json={"phone": phone}).json()["demo_code"]
    r = client.post("/auth/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def villager_sign_in(client, phone="9000000001", village_id="V001"):
    code = client.post("/public/auth/request-code", json={"phone": phone}).json()["demo_code"]
    r = client.post("/public/auth/verify", json={"phone": phone, "code": code, "village_id": village_id})
    assert r.status_code == 200, r.text
    return r.json()
