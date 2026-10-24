"""Relief centres: official list, OpenStreetMap candidates a GP designates, centres added on the map."""
import pytest

from backend.app import config, notify
from backend.app.services import shelters
from backend.tests.conftest import BELTHANGADY, SULLIA, app_client, sign_in, villager_sign_in

OFFICIAL = """shelter_id,name,name_kn,kind,lat,lon,capacity,phone,taluk_id
MPCS-1,Cyclone Shelter Ujre,,cyclone shelter,12.992,75.331,500,08256000000,
"""
CANDIDATES = """shelter_id,name,name_kn,kind,lat,lon,village_id,taluk_id,district
osm-n1,Govt Higher Primary School Ujre,ಸರ್ಕಾರಿ ಶಾಲೆ ಉಜಿರೆ,school,12.990,75.329,KA001,dakshina-kannada:belthangady,Dakshina Kannada
osm-n2,Community Hall Laila,,community hall,12.801,75.201,KA003,dakshina-kannada:belthangady,Dakshina Kannada
osm-w3,Govt High School Subramanya,,school,12.671,75.621,KA004,dakshina-kannada:sullia,Dakshina Kannada
"""


@pytest.fixture
def files(world):
    config.SHELTERS_CSV.write_text(OFFICIAL, encoding="utf-8")
    config.SHELTER_CANDIDATES_CSV.write_text(CANDIDATES, encoding="utf-8")
    return world


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "push", lambda roles, title, msg, **k: sent.append(title) or 1)
    return sent


def test_sync_loads_both_files_and_keeps_decisions(files):
    with app_client():
        pass                                                      # start-up runs the sync
    assert shelters.sync_from_csv() == {"designated": 1, "candidates": 3}
    off = shelters.get("MPCS-1")
    assert off["designated"] and off["taluk_id"] == BELTHANGADY and off["source"] == "official"
    shelters.update("osm-n1", "GP", designated=True, capacity=120)
    shelters.update("osm-n1", "GP", is_open=True, occupancy=30)
    # OpenStreetMap renames the school and drops the Laila hall; the GP's decisions stay.
    config.SHELTER_CANDIDATES_CSV.write_text(CANDIDATES.replace("Govt Higher Primary School Ujre", "GHPS Ujre")
                                             .replace("osm-n2,Community Hall Laila,,community hall,12.801,75.201,KA003,dakshina-kannada:belthangady,Dakshina Kannada\n", ""),
                                             encoding="utf-8")
    shelters.sync_from_csv()
    s = shelters.get("osm-n1")
    assert (s["name"], s["designated"], s["capacity"], s["occupancy"]) == ("GHPS Ujre", True, 120, 30)
    assert shelters.get("osm-n2") is None


def test_villagers_see_designated_centres_only(files):
    with app_client() as gp, app_client() as pub:
        sign_in(gp)
        r = pub.get("/public/shelters/KA001").json()
        assert [s["shelter_id"] for s in r["shelters"]] == ["MPCS-1"]          # the school is only a candidate
        assert r["any_open"] is False
        gp.patch("/shelters/osm-n1", json={"designated": True, "capacity": 120})
        gp.patch("/shelters/osm-n1", json={"is_open": True})
        r = pub.get("/public/shelters/KA001").json()
        assert r["shelters"][0]["shelter_id"] == "osm-n1" and r["any_open"] is True   # open first
        mine = pub.get("/public/shelters/KA001", params={"lat": 12.992, "lon": 75.331}).json()
        assert mine["measured_from"] == "your_location"


def test_designate_rules(files):
    with app_client() as gp:
        sign_in(gp)
        assert gp.patch("/shelters/osm-n1", json={"is_open": True}).status_code == 409         # not designated
        assert gp.patch("/shelters/osm-n1", json={"designated": True}).status_code == 409     # needs capacity
        r = gp.patch("/shelters/osm-n1", json={"designated": True, "capacity": 120, "phone": "0825 600"}).json()
        assert r["status"] == "closed" and r["phone"] == "0825 600"
        assert gp.patch("/shelters/osm-n1", json={"occupancy": 5}).status_code == 409         # open it first
        gp.patch("/shelters/osm-n1", json={"is_open": True, "occupancy": 40})
        r = gp.patch("/shelters/osm-n1", json={"designated": False}).json()                    # un-mark
        assert (r["status"], r["is_open"], r["occupancy"]) == ("candidate", False, 0)
        assert gp.patch("/shelters/MPCS-1", json={"designated": False}).status_code == 409    # official stays
        assert gp.patch("/shelters/osm-n1", json={}).status_code == 422


def test_only_own_taluk_and_only_gp(files):
    with app_client() as bel, app_client() as sul, app_client() as ngo:
        sign_in(bel, "Belthangady GP", "9876543210", taluk_id=BELTHANGADY)
        sign_in(sul, "Sullia GP", "9876500000", taluk_id=SULLIA)
        sign_in(ngo, "NGO", "9123456780", role="ngo", taluk_id=None, district="Dakshina Kannada")
        assert sul.patch("/shelters/osm-n1", json={"designated": True, "capacity": 10}).status_code == 404
        assert ngo.patch("/shelters/osm-n1", json={"designated": True, "capacity": 10}).status_code == 403
        assert [c["shelter_id"] for c in bel.get("/shelters/candidates").json()] == ["osm-n2", "osm-n1"] or \
            sorted(c["shelter_id"] for c in bel.get("/shelters/candidates").json()) == ["osm-n1", "osm-n2"]
        assert [c["shelter_id"] for c in sul.get("/shelters/candidates").json()] == ["osm-w3"]
        assert [c["shelter_id"] for c in bel.get("/shelters/candidates", params={"q": "laila"}).json()] == ["osm-n2"]
        s = ngo.get("/shelters").json()
        assert s["totals"]["centres"] == 1 and [t["taluk_id"] for t in s["taluks"]] == [BELTHANGADY, SULLIA]
        assert s["totals"]["candidates"] == 3


def test_gp_adds_a_centre_on_the_map(files, pushes):
    with app_client() as bel:
        sign_in(bel)
        r = bel.post("/shelters", json={"name": "Temple hall", "lat": 12.80, "lon": 75.205, "capacity": 80})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["source"] == "gp" and s["designated"] and s["taluk_id"] == BELTHANGADY and s["added_by"] == "Ujire GP"
        assert bel.post("/shelters", json={"name": "Far away", "lat": 12.67, "lon": 75.62, "capacity": 50}).status_code == 403
        assert bel.post("/shelters", json={"name": "x", "lat": 12.8, "lon": 75.2, "capacity": 0}).status_code == 422


def test_reported_at_shelter_from_family_reports(files):
    with app_client() as gp, app_client() as v:
        sign_in(gp)
        villager_sign_in(v)
        v.post("/public/report", json={"village_id": "KA001", "at_shelter": 4})
        g = gp.get("/shelters").json()["taluks"]
    assert g[0]["taluk_id"] == BELTHANGADY and g[0]["reported_at_shelter"] == 4


def test_pushes_when_opened_and_filling_up(files, pushes):
    with app_client() as gp:
        sign_in(gp)
        gp.patch("/shelters/MPCS-1", json={"is_open": True})
        for n in (100, 460, 470, 500, 510):
            gp.patch("/shelters/MPCS-1", json={"occupancy": n})
    assert pushes == ["Relief centre opened: Belthangady", "Relief centre nearly full: Belthangady",
                      "Relief centre FULL: Belthangady"]


def test_far_open_centre_is_not_put_first(files, monkeypatch):
    monkeypatch.setattr(shelters, "REACHABLE_KM", 1.0)
    shelters.sync_from_csv()
    shelters.update("osm-n2", "GP", designated=True, capacity=50)
    shelters.update("osm-n2", "GP", is_open=True)                  # Laila hall, ~23 km from Ujre
    near = shelters.nearest(12.99, 75.33)
    assert near[0]["shelter_id"] == "MPCS-1" and not any(s["reachable"] for s in near)


def test_distance_is_sensible():
    assert 4 < shelters.distance_km(12.995, 75.33, 12.985, 75.29) < 5
