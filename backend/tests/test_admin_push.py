"""The admin gives Panchayat access; approved warnings ring villagers' phones (Web Push, optional ntfy)."""
import types

import pytest

from backend.app import auth, config, database, push
from backend.tests.conftest import BELTHANGADY, SULLIA, app_client, sign_in

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}


def guest(c, phone="9000012345"):
    code = c.post("/auth/request-code", json={"phone": phone}).json()["demo_code"]
    assert c.post("/auth/verify", json={"phone": phone, "code": code}).status_code == 200


# ---------- admin ----------

def test_admin_makes_a_guest_a_panchayat_official(monkeypatch):
    monkeypatch.setattr(config, "OPEN_SIGNIN", "viewer")
    with app_client() as admin, app_client() as g:
        me = sign_in(admin, "State admin", "9111111111", role="admin", taluk_id=None)
        assert me["role"] == "admin" and me["area"] == "All of Karnataka"
        guest(g)
        assert g.post("/alerts/generate").status_code == 403                        # guest: read-only
        listed = admin.get("/admin/officials").json()["officials"]
        assert any(o["guest"] and o["phone"].endswith("2345") for o in listed)
        r = admin.post("/admin/officials", json={"phone": "9000012345", "name": "Guest ····2345", "role": "gp",
                                                  "taluk_id": BELTHANGADY})
        assert r.status_code == 422                                                 # needs a real name
        assert admin.post("/admin/officials", json={"phone": "9000012345", "name": "Ravi", "role": "gp"}).status_code == 422
        r = admin.post("/admin/officials", json={"phone": "9000012345", "name": "Ravi", "role": "gp", "taluk_id": BELTHANGADY})
        assert r.status_code == 200 and r.json()["guest"] is False
        assert g.post("/alerts/generate").status_code == 200                        # same session, now a GP
        assert admin.delete("/admin/officials/9000012345").json() == {"removed": True}
        assert g.get("/risk").status_code == 401                                    # signed out everywhere


def test_only_the_admin_manages_staff():
    with app_client() as gp, app_client() as admin:
        sign_in(gp)                                                                 # an ordinary GP
        assert gp.get("/admin/officials").status_code == 403
        assert gp.post("/admin/officials", json={"phone": "9000000009", "name": "Me", "role": "gp",
                                                  "taluk_id": BELTHANGADY}).status_code == 403
        sign_in(admin, "State admin", "9111111111", role="admin", taluk_id=None)
        assert admin.delete("/admin/officials/9111111111").status_code == 403       # admins only via settings
        assert admin.post("/admin/officials", json={"phone": "9111111111", "name": "Xavier", "role": "ngo"}).status_code == 403


def test_admin_acts_as_gp_in_every_taluk():
    with app_client() as admin:
        sign_in(admin, "State admin", "9111111111", role="admin", taluk_id=None)
        for tid in (BELTHANGADY, SULLIA):
            r = admin.post(f"/alerts/draft/{tid}?simulate_high=true")
            assert r.status_code == 200, r.text


def test_admin_from_officials_setting():
    added, problems = auth.seed_officials("9111111111, State admin, admin")
    assert added[0]["role"] == "admin" and not problems


# ---------- villagers' alarms ----------

@pytest.fixture
def sent(monkeypatch):
    out = []

    def fake_send(row, payload):
        out.append((row["village_id"], payload))
        return 410 if row["endpoint"].endswith("gone") else 201
    monkeypatch.setattr(push, "_send_one", fake_send)
    return out


def test_keys_are_made_once_and_kept():
    pub, priv = push.keys()
    assert len(pub) > 80 and push.keys() == (pub, priv)
    with app_client() as c:
        assert c.get("/public/push/key").json()["public_key"] == pub


def test_subscribe_checks_input():
    with app_client() as c:
        assert c.post("/public/push/subscribe", json={"subscription": SUB, "village_id": "nope"}).status_code == 422
        assert c.post("/public/push/subscribe", json={"subscription": {"endpoint": "http://x"},
                                                      "village_id": "KA001"}).status_code == 422
        r = c.post("/public/push/subscribe", json={"subscription": SUB, "village_id": "KA001"}).json()
        assert r["taluk_id"] == BELTHANGADY and r["public_topic"] is None
        assert push.count() == 1


def test_approved_warning_rings_phones_in_that_taluk(sent, world):
    push.subscribe(SUB, "KA001", "kn")                                            # Ujre, Belthangady
    push.subscribe({**SUB, "endpoint": SUB["endpoint"] + "en"}, "KA002", "en")     # Dharmasthala, Belthangady
    push.subscribe({**SUB, "endpoint": SUB["endpoint"] + "gone"}, "KA003")         # unsubscribed phone
    push.subscribe({**SUB, "endpoint": SUB["endpoint"] + "s"}, "KA004")            # Subramanya, Sullia: not rung
    world.rain("13.00_75.25", past=200)
    with app_client() as c:
        sign_in(c)
        a = c.post("/alerts/generate").json()["alerts"][0]
        r = c.post(f"/alerts/{a['id']}/approve", json={"note": ""}).json()
        assert r["phones_alerted"] == 3
    assert sorted(v for v, _ in sent) == ["KA001", "KA002", "KA003"]
    kn = next(p for v, p in sent if v == "KA001")
    en = next(p for v, p in sent if v == "KA002")
    assert "ಎಚ್ಚರಿಕೆ" in kn["title"] and kn["body"] == a["message_kn"] and kn["url"].startswith("/villager/?v=KA001&alarm=")
    assert en["title"].endswith("Flood / landslide warning") and en["body"] == a["message_en"]
    assert push.count() == 3                                                       # the 'gone' phone was removed


def test_test_alerts_ring_only_demo_phones(sent):
    push.subscribe(SUB, "KA001", demo=False)
    push.subscribe({**SUB, "endpoint": SUB["endpoint"] + "d"}, "KA002", demo=True)
    with app_client() as c:
        sign_in(c)
        a = c.post(f"/alerts/draft/{BELTHANGADY}?simulate_high=true").json()
        r = c.post(f"/alerts/{a['id']}/approve", json={"note": ""}).json()
        assert r["phones_alerted"] == "demo phones only"
    assert [v for v, _ in sent] == ["KA002"] and sent[0][1]["title"].startswith("ಪರೀಕ್ಷೆ")
    assert sent[0][1]["url"].endswith("&demo=true")


def test_public_ntfy_alarm_when_configured(sent, monkeypatch, world):
    monkeypatch.setattr(config, "NTFY_TOPIC_PUBLIC", "ka-flood")
    posts = []
    monkeypatch.setattr(push.requests, "post",
                        lambda url, data, timeout, headers: posts.append((url, headers)) or types.SimpleNamespace(status_code=200))
    with app_client() as c:
        assert c.get("/public/push/topic/KA001").json()["topic"] == "ka-flood-dakshina-kannada-belthangady"
        world.rain("13.00_75.25", past=200)
        sign_in(c)
        a = c.post("/alerts/generate").json()["alerts"][0]
        c.post(f"/alerts/{a['id']}/approve", json={"note": ""})
        assert c.get("/health").json()["villager_alarms"].endswith("'ka-flood-<taluk>'")
    assert posts and posts[0][0].endswith("/ka-flood-dakshina-kannada-belthangady") and posts[0][1]["Priority"] == "5"
