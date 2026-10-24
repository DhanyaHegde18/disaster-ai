"""Staff see and act on their own area only: a GP their taluk, an NGO their district, no area = the state."""
import pytest

from backend.app import auth
from backend.tests.conftest import BELTHANGADY, SULLIA, UDUPI, app_client, sign_in, villager_sign_in


@pytest.fixture
def wet(world):
    world.rain("13.00_75.25", past=60, future=260)      # Belthangady HIGH
    world.rain("12.75_75.50", past=200, future=10)      # Sullia HIGH
    world.rain("13.25_74.75", past=110, future=20)      # Udupi MEDIUM
    return world


def test_gp_sees_only_their_taluk(wet):
    with app_client() as c:
        me = sign_in(c, taluk_id=BELTHANGADY)
        assert me["area"] == "Belthangady taluk, Dakshina Kannada"
        r = c.get("/risk").json()
        assert [t["taluk_id"] for t in r["taluks"]] == [BELTHANGADY]
        assert r["summary"] == {"HIGH": 2, "MEDIUM": 0, "LOW": 1}               # Ujre + Dharmasthala HIGH, Laila LOW
        assert {v["name"]: v["level"] for v in r["villages"]} == {"Ujre": "HIGH", "Dharmasthala": "HIGH", "Laila": "LOW"}
        assert c.get(f"/risk/taluk/{SULLIA}").status_code == 404
        created = c.post("/alerts/generate").json()["alerts"]
        assert [a["taluk_id"] for a in created] == [BELTHANGADY]                 # not Sullia's


def test_ngo_district_and_state_level(wet):
    with app_client() as ngo, app_client() as state:
        sign_in(ngo, "Red Cross DK", "9123456780", role="ngo", taluk_id=None, district="Dakshina Kannada")
        r = ngo.get("/risk").json()
        assert r["area"] == "Dakshina Kannada district" and {t["taluk_id"] for t in r["taluks"]} == {BELTHANGADY, SULLIA}
        assert "villages" not in r                                                 # village list only for one taluk
        sign_in(state, "State room", "9000011111", taluk_id=None)
        r = state.get("/risk").json()
        assert r["area"] == "All of Karnataka" and len(r["taluks"]) == 3
        assert r["taluks"][2]["taluk_id"] == UDUPI and r["taluks"][2]["level"] == "MEDIUM"
        assert len(state.post("/alerts/generate").json()["alerts"]) == 2          # both HIGH taluks


def test_alert_actions_limited_to_own_taluk(wet):
    with app_client() as bel, app_client() as sul, app_client() as ngo:
        sign_in(bel, "Belthangady GP", "9876543210", taluk_id=BELTHANGADY)
        sign_in(sul, "Sullia GP", "9876500000", taluk_id=SULLIA)
        sign_in(ngo, "NGO Udupi", "9123456780", role="ngo", taluk_id=None, district="Udupi")
        a = bel.post("/alerts/generate").json()["alerts"][0]
        assert [x["id"] for x in sul.get("/alerts").json()] == []
        assert sul.post(f"/alerts/{a['id']}/approve", json={}).status_code == 404
        assert sul.put(f"/alerts/{a['id']}", json={"message_en": "x"}).status_code == 404
        assert bel.post(f"/alerts/{a['id']}/approve", json={}).json()["status"] == "approved"
        assert ngo.get("/alerts").json() == []                                     # Udupi NGO: not their district
        assert sul.post(f"/alerts/draft/{BELTHANGADY}?simulate_high=true").status_code == 404


def test_relief_reports_scoped_and_ngo_never_sees_phones(wet):
    with app_client() as v1, app_client() as v2, app_client() as bel, app_client() as sul, app_client() as ngo:
        villager_sign_in(v1, "9000000001", "KA001")
        v1.post("/public/report", json={"village_id": "KA001", "unknown": 2, "needs": ["rescue"]})
        villager_sign_in(v2, "9000000002", "KA004")
        v2.post("/public/report", json={"village_id": "KA004", "at_shelter": 3})
        sign_in(bel, "Belthangady GP", "9876543210", taluk_id=BELTHANGADY)
        sign_in(sul, "Sullia GP", "9876500000", taluk_id=SULLIA)
        sign_in(ngo, "Red Cross DK", "9123456780", role="ngo", taluk_id=None, district="Dakshina Kannada")
        assert [x["name"] for x in bel.get("/relief/summary").json()["villages"]] == ["Ujre"]
        assert [x["name"] for x in sul.get("/relief/summary").json()["villages"]] == ["Subramanya"]
        s = ngo.get("/relief/summary").json()
        assert s["totals"]["families"] == 2 and "+91" not in str(s)
        assert ngo.get("/relief/reports/KA001").status_code == 403
        assert sul.get("/relief/reports/KA001").status_code == 404                # another taluk
        assert bel.get("/relief/reports/KA001").json()["families"][0]["phone"] == "+919000000001"
        assert sul.post("/relief/reports/9000000001/handled").status_code == 404
        assert bel.post("/relief/reports/9000000001/handled").json() == {"handled": True, "by": "Belthangady GP"}


def test_add_official_validates_area():
    with pytest.raises(auth.AuthError):
        auth.add_official("9876543210", "X", "gp", taluk_id="nowhere:none")
    o = auth.add_official("9876543210", "X", "ngo", district="udupi")
    assert o["district"] == "Udupi" and o["area"] == "Udupi district"
    o = auth.add_official("9876543210", "X", "gp", taluk_id=SULLIA)
    assert o["district"] == "Dakshina Kannada" and o["taluk_name"] == "Sullia"
