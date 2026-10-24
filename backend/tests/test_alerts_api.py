"""Alerts per taluk: drafting, no duplicates in a day, testing with simulated alerts, review flow."""
from backend.tests.conftest import BELTHANGADY, SULLIA, app_client, sign_in


def test_generate_drafts_one_per_high_taluk_once_a_day(world):
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as c:
        sign_in(c, taluk_id=None)
        first = c.post("/alerts/generate").json()
        assert first["created"] == 1
        a = first["alerts"][0]
        assert a["taluk_id"] == BELTHANGADY and a["taluk_name"] == "Belthangady" and a["district"] == "Dakshina Kannada"
        assert a["risk"]["places"][:2] == ["Ujre", "Dharmasthala"]               # biggest villages in the wet square
        assert "Belthangady" in a["message_en"] and "Ujre" in a["message_en"]
        assert c.post("/alerts/generate").json()["created"] == 0                  # already one today


def test_low_taluk_needs_simulation(world):
    with app_client() as c:
        sign_in(c, taluk_id=SULLIA)
        assert c.post(f"/alerts/draft/{SULLIA}").status_code == 409
        a = c.post(f"/alerts/draft/{SULLIA}?simulate_high=true").json()
        assert a["simulated"] is True and a["level"] == "HIGH" and "250" in a["message_en"]
        assert c.post("/alerts/draft/nowhere:none?simulate_high=true").status_code == 404


def test_edit_then_approve(world):
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as c:
        sign_in(c)
        a = c.post("/alerts/generate").json()["alerts"][0]
        e = c.put(f"/alerts/{a['id']}", json={"message_en": "Edited warning for Belthangady."}).json()
        assert e["edited"] is True and e["message_en"] == "Edited warning for Belthangady."
        assert c.post(f"/alerts/{a['id']}/approve", json={}).json()["status"] == "approved"
        assert c.post(f"/alerts/{a['id']}/approve", json={}).status_code == 409   # already reviewed
        assert c.put(f"/alerts/{a['id']}", json={"message_en": "x"}).status_code == 409


def test_ngo_reads_approved_only_and_cannot_review(world):
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as gp, app_client() as ngo:
        sign_in(gp)
        sign_in(ngo, "Red Cross", "9123456780", role="ngo", taluk_id=None, district="Dakshina Kannada")
        a = gp.post("/alerts/generate").json()["alerts"][0]
        assert ngo.get("/alerts").json() == [] and ngo.get(f"/alerts/{a['id']}").status_code == 404
        assert ngo.post(f"/alerts/{a['id']}/approve", json={}).status_code == 403
        gp.post(f"/alerts/{a['id']}/approve", json={})
        assert [x["id"] for x in ngo.get("/alerts?status=pending").json()] == [a["id"]]   # forced to approved
