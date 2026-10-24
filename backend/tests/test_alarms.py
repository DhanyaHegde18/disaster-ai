"""Phone alerts (ntfy, mocked) and reminders until someone acts."""
from datetime import datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

from backend.app import config, database, notify
from backend.app.jobs import escalation
from backend.app.routers import alerts as alerts_router
from backend.app.services.alerts import generate_for_snapshot
from backend.tests.conftest import sign_in, villager_sign_in

SNAP = {"generated_at": "2026-08-01T09:00:00+05:30", "villages": [
    {"village_id": "V001", "name": "Ujire", "district": "Dakshina Kannada", "level": "HIGH",
     "past_3d_mm": 60.0, "forecast_3d_mm": 260.0, "reasons": ["test"], "daily_mm": []}]}
CFG = {"villages": [{"village_id": "V001", "name": "Ujire", "name_kn": "ಉಜಿರೆ", "district": "Dakshina Kannada"}],
       "calibrated_on": "test", "thresholds_mm": {}}


class Resp:
    status_code, text = 200, "ok"


@pytest.fixture
def pushes(tmp_path, monkeypatch):
    """Configure topics and capture every push instead of sending it."""
    sent = []
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "OTP_RESEND_S", 0)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "gp-secret-topic")
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", "ngo-secret-topic")
    monkeypatch.setattr(config, "rule_config", lambda: CFG)
    monkeypatch.setattr(alerts_router, "_cached_or_fresh", lambda: SNAP)

    def fake_post(url, data, timeout, headers):
        sent.append({"topic": url.rsplit("/", 1)[1], "title": headers["Title"],
                     "priority": int(headers["Priority"]), "body": data.decode()})
        return Resp()
    monkeypatch.setattr(notify.requests, "post", fake_post)
    database.init_db()
    return sent


def app_client():
    from backend.app.main import app
    return TestClient(app)


def report_rescue(c, phone="9000000001", needs=("rescue",)):
    villager_sign_in(c, phone)
    return c.post("/public/report", json={"village_id": "V001", "at_shelter": 2, "unknown": 1, "needs": list(needs)})


def test_rescue_request_pushes_to_gp_and_ngo(pushes):
    with app_client() as c:
        assert report_rescue(c).status_code == 200
    assert {p["topic"] for p in pushes} == {"gp-secret-topic", "ngo-secret-topic"}
    assert all(p["priority"] == notify.URGENT and "RESCUE" in p["title"] for p in pushes)


def test_report_without_rescue_is_quiet(pushes):
    with app_client() as c:
        report_rescue(c, needs=("water",))
    assert pushes == []


def test_push_failure_never_breaks_the_report(pushes, monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("no network")
    monkeypatch.setattr(notify.requests, "post", down)
    with app_client() as c:
        r = report_rescue(c)
    assert r.status_code == 200 and r.json()["saved"] is True


def test_new_real_alert_pushes_to_gp_only(pushes):
    generate_for_snapshot(SNAP)
    assert [p["topic"] for p in pushes] == ["gp-secret-topic"]
    assert "waiting" in pushes[0]["title"].lower() and pushes[0]["priority"] == notify.HIGH


def test_simulated_draft_does_not_push(pushes):
    with app_client() as c:
        sign_in(c)
        c.post("/alerts/draft/V001?simulate_high=true")
    assert pushes == []


def test_pending_alert_reminders_until_reviewed(pushes):
    alert = generate_for_snapshot(SNAP)[0]                     # first push at draft time
    now = datetime.now().astimezone()
    assert escalation.check_once(now + timedelta(minutes=5))["alerts"] == 0          # too soon
    assert escalation.check_once(now + timedelta(minutes=16))["alerts"] == 1         # reminder
    assert pushes[-1]["priority"] == notify.URGENT and "NOT been warned" in pushes[-1]["body"]
    database.review(alert["id"], "approved", "Ujire GP", None)
    assert escalation.check_once(now + timedelta(minutes=60))["alerts"] == 0         # reviewed: stop


def test_reminders_stop_after_max(pushes, monkeypatch):
    monkeypatch.setattr(config, "ESCALATE_MAX_TIMES", 3)
    generate_for_snapshot(SNAP)
    t = datetime.now().astimezone()
    for i in range(1, 10):
        escalation.check_once(t + timedelta(minutes=16 * i))
    assert len(pushes) == 3


def test_rescue_reminders_until_marked_handled(pushes):
    with app_client() as v, app_client() as gp, app_client() as ngo:
        report_rescue(v)
        sign_in(gp, "Ujire GP", "9876543210")
        sign_in(ngo, "Red Cross", "9123456780", role="ngo")
        first = len(pushes)
        t = datetime.now().astimezone()
        assert escalation.check_once(t + timedelta(minutes=16))["rescues"] == 1
        assert len(pushes) == first + 2 and "reminder 1" in pushes[-1]["body"]

        s = ngo.get("/relief/summary").json()["totals"]
        assert (s["rescue_requests"], s["rescue_handled"]) == (1, 0)
        assert ngo.post("/relief/reports/9000000001/handled").status_code == 403     # NGOs can't close it
        r = gp.post("/relief/reports/9000000001/handled").json()
        assert r == {"handled": True, "by": "Ujire GP"}
        s = ngo.get("/relief/summary").json()["totals"]
        assert (s["rescue_requests"], s["rescue_handled"]) == (0, 1)
        assert escalation.check_once(t + timedelta(minutes=60))["rescues"] == 0      # handled: stop

        # A new rescue report from the same family re-opens it and alerts again.
        before = len(pushes)
        v.post("/public/report", json={"village_id": "V001", "unknown": 2, "needs": ["rescue"]})
        assert len(pushes) == before + 2
        assert ngo.get("/relief/summary").json()["totals"]["rescue_requests"] == 1


def test_no_topics_means_no_reminders(pushes, monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "")
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", "")
    generate_for_snapshot(SNAP)
    assert escalation.check_once(datetime.now().astimezone() + timedelta(hours=1)) == {"alerts": 0, "rescues": 0}
    assert pushes == []
