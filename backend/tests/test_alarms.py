"""Phone alerts (ntfy, mocked): a topic per taluk / district, and reminders until someone acts."""
from datetime import datetime, timedelta

import pytest
import requests

from backend.app import config, database, notify
from backend.app.jobs import escalation
from backend.tests.conftest import BELTHANGADY, app_client, sign_in, villager_sign_in

GP_T, NGO_T = "gp-secret", "ngo-secret"
BEL_GP, DK_NGO = "gp-secret-dakshina-kannada-belthangady", "ngo-secret-dakshina-kannada"


class Resp:
    status_code, text = 200, "ok"


@pytest.fixture
def pushes(world, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", GP_T)
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", NGO_T)

    def fake_post(url, data, timeout, headers):
        sent.append({"topic": url.rsplit("/", 1)[1], "title": headers["Title"],
                     "priority": int(headers["Priority"]), "body": data.decode()})
        return Resp()
    monkeypatch.setattr(notify.requests, "post", fake_post)
    database.init_db()
    return sent


def topics(sent):
    return {p["topic"] for p in sent}


def report_rescue(c, phone="9000000001", village="KA001", needs=("rescue",)):
    villager_sign_in(c, phone, village)
    return c.post("/public/report", json={"village_id": village, "at_shelter": 2, "unknown": 1, "needs": list(needs)})


def test_topic_for_each_person(monkeypatch):
    assert notify.topic_for_user({"role": "gp", "taluk_id": BELTHANGADY}) is None          # no topics set
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", GP_T)
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", NGO_T)
    assert notify.topic_for_user({"role": "gp", "taluk_id": BELTHANGADY}) == BEL_GP
    assert notify.topic_for_user({"role": "ngo", "district": "Dakshina Kannada"}) == DK_NGO
    assert notify.topic_for_user({"role": "gp"}) == GP_T                                  # state level
    assert len(notify.topic_for_user({"role": "gp", "taluk_id": "chikkamagaluru:narasimharajapura"})) <= 64


def test_rescue_rings_that_taluk_and_district_only(pushes):
    with app_client() as c:
        assert report_rescue(c).status_code == 200
    assert topics(pushes) == {GP_T, BEL_GP, NGO_T, DK_NGO}
    assert all(p["priority"] == notify.URGENT and "RESCUE" in p["title"] and "Ujre" in p["title"] for p in pushes)


def test_me_shows_my_topic(pushes):
    with app_client() as c:
        assert sign_in(c)["alert_topic"] == BEL_GP


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


def test_new_real_alert_pushes_to_that_taluks_gp(pushes, world):
    world.rain("12.75_75.50", past=60, future=260)                          # Sullia HIGH
    with app_client() as c:
        sign_in(c, taluk_id=None)
        c.post("/alerts/generate")
    assert topics(pushes) == {GP_T, "gp-secret-dakshina-kannada-sullia"}
    assert "waiting" in pushes[0]["title"].lower() and pushes[0]["priority"] == notify.HIGH


def test_simulated_draft_does_not_push(pushes):
    with app_client() as c:
        sign_in(c)
        c.post(f"/alerts/draft/{BELTHANGADY}?simulate_high=true")
    assert pushes == []


def test_pending_alert_reminders_until_reviewed(pushes, world):
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as c:
        sign_in(c)
        alert = c.post("/alerts/generate").json()["alerts"][0]
    now = datetime.now().astimezone()
    assert escalation.check_once(now + timedelta(minutes=5))["alerts"] == 0          # too soon
    assert escalation.check_once(now + timedelta(minutes=16))["alerts"] == 1         # reminder
    assert pushes[-1]["priority"] == notify.URGENT and "NOT been warned" in pushes[-1]["body"]
    database.review(alert["id"], "approved", "Ujire GP", None)
    assert escalation.check_once(now + timedelta(minutes=60))["alerts"] == 0         # reviewed: stop


def test_reminders_stop_after_max(pushes, world, monkeypatch):
    monkeypatch.setattr(config, "ESCALATE_MAX_TIMES", 3)
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as c:
        sign_in(c)
        c.post("/alerts/generate")
    t = datetime.now().astimezone()
    for i in range(1, 10):
        escalation.check_once(t + timedelta(minutes=16 * i))
    assert len(pushes) == 3 * 2                    # 3 times, to the state topic and the taluk topic


def test_rescue_reminders_until_marked_handled(pushes):
    with app_client() as v, app_client() as gp, app_client() as ngo:
        report_rescue(v)
        sign_in(gp, "Ujire GP", "9876543210")
        sign_in(ngo, "Red Cross", "9123456780", role="ngo", taluk_id=None, district="Dakshina Kannada")
        first = len(pushes)
        t = datetime.now().astimezone()
        assert escalation.check_once(t + timedelta(minutes=16))["rescues"] == 1
        assert len(pushes) == first + 4 and "reminder 1" in pushes[-1]["body"]
        assert ngo.post("/relief/reports/9000000001/handled").status_code == 403     # NGOs can't close it
        assert gp.post("/relief/reports/9000000001/handled").json() == {"handled": True, "by": "Ujire GP"}
        s = ngo.get("/relief/summary").json()["totals"]
        assert (s["rescue_requests"], s["rescue_handled"]) == (0, 1)
        assert escalation.check_once(t + timedelta(minutes=60))["rescues"] == 0      # handled: stop
        before = len(pushes)                                                          # a new request re-opens it
        v.post("/public/report", json={"village_id": "KA001", "unknown": 2, "needs": ["rescue"]})
        assert len(pushes) == before + 4


def test_no_topics_means_no_reminders(pushes, world, monkeypatch):
    world.rain("13.00_75.25", past=60, future=260)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "")
    monkeypatch.setattr(config, "NTFY_TOPIC_NGO", "")
    with app_client() as c:
        sign_in(c)
        c.post("/alerts/generate")
    assert escalation.check_once(datetime.now().astimezone() + timedelta(hours=1)) == {"alerts": 0, "rescues": 0}
    assert pushes == []


def test_notification_links_follow_the_address_staff_use(pushes, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    clicks = []
    real = notify.requests.post
    monkeypatch.setattr(notify.requests, "post", lambda url, data, timeout, headers: clicks.append(headers["Click"]) or real(url, data=data, timeout=timeout, headers=headers))
    with app_client() as c:
        sign_in(c)
        assert notify.public_url() == "http://127.0.0.1:8000"                       # nothing learned yet
        c.get("/auth/me", headers={"host": "172.19.37.23:8000"})                    # Wi-Fi address
        assert notify.public_url() == "http://172.19.37.23:8000"
        c.get("/auth/me", headers={"host": "when-exceed.trycloudflare.com", "x-forwarded-proto": "https"})
        assert notify.public_url() == "https://when-exceed.trycloudflare.com"
        c.get("/auth/me", headers={"host": "172.19.37.23:8000"})                    # https is kept
        assert notify.public_url() == "https://when-exceed.trycloudflare.com"
        c.get("/auth/me", headers={"host": "hawkeye.tail1234.ts.net", "x-forwarded-proto": "https"})
        report_rescue(c)
    assert clicks and all(u.startswith("https://hawkeye.tail1234.ts.net/") for u in clicks)


def test_strangers_cannot_change_the_links(pushes, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    with app_client() as c:
        c.get("/auth/me", headers={"host": "evil.example", "x-forwarded-proto": "https"})   # not signed in
        c.get("/public/districts", headers={"host": "evil.example"})
    assert notify.public_url() == "http://127.0.0.1:8000"


def test_env_public_url_wins(pushes, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://fixed.example")
    with app_client() as c:
        sign_in(c)
        c.get("/auth/me", headers={"host": "other.trycloudflare.com", "x-forwarded-proto": "https"})
    assert notify.public_url() == "https://fixed.example"
