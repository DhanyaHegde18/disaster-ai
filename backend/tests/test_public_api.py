"""Villager-facing endpoints: choosing a village, and approved warnings only."""
from backend.tests.conftest import BELTHANGADY, SULLIA, app_client, sign_in


def test_districts_and_village_picker():
    with app_client() as c:
        d = c.get("/public/districts").json()
        assert [x["name"] for x in d] == ["Dakshina Kannada", "Udupi"] and d[0]["name_kn"] == "ದಕ್ಷಿಣ ಕನ್ನಡ"
        assert [v["name"] for v in c.get("/public/villages", params={"taluk_id": BELTHANGADY}).json()] == \
            ["Dharmasthala", "Laila", "Ujre"]
        found = c.get("/public/villages", params={"q": "ujire"}).json()
        assert found[0]["village_id"] == "KA001" and found[0]["taluk"] == "Belthangady"
        assert c.get("/public/villages").status_code == 422
        assert c.get("/public/villages", params={"taluk_id": "no:where"}).status_code == 404
        v = c.get("/public/village/KA004").json()
        assert v["taluk_id"] == SULLIA and v["district_kn"] == "ದಕ್ಷಿಣ ಕನ್ನಡ"
        assert c.get("/public/village/NOPE").status_code == 404


def test_only_approved_alerts_for_the_villages_taluk(world):
    world.rain("13.00_75.25", past=60, future=260)
    with app_client() as gp, app_client() as pub:
        sign_in(gp)
        a = gp.post("/alerts/generate").json()["alerts"][0]
        assert pub.get("/public/status/KA003").json()["active"] == []          # pending: not shown
        gp.post(f"/alerts/{a['id']}/approve", json={})
        laila = pub.get("/public/status/KA003").json()                         # same taluk, other square
        assert [x["id"] for x in laila["active"]] == [a["id"]] and laila["village"]["name"] == "Laila"
        assert pub.get("/public/status/KA004").json()["active"] == []          # Sullia: not this alert
        assert pub.get("/public/status/NOPE").status_code == 404


def test_simulated_only_in_demo_mode():
    with app_client() as gp, app_client() as pub:
        sign_in(gp)
        a = gp.post(f"/alerts/draft/{BELTHANGADY}?simulate_high=true").json()
        gp.post(f"/alerts/{a['id']}/approve", json={})
        assert pub.get("/public/status/KA001").json()["active"] == []
        demo = pub.get("/public/status/KA001?demo=true").json()["active"]
        assert demo[0]["test"] is True
