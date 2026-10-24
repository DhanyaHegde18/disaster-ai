"""Villages, taluks and spelling-tolerant search."""
from backend.app import areas
from backend.tests.conftest import BELTHANGADY


def test_lookup_and_taluks():
    a = areas.get()
    assert len(a.villages) == 5 and a.village("KA001")["name"] == "Ujre"
    assert sorted(a.taluks_in_district("dakshina kannada")) == ["dakshina-kannada:belthangady", "dakshina-kannada:sullia"]
    assert a.cells_by_taluk[BELTHANGADY] == {"13.00_75.25", "12.75_75.25"}


def test_search_tolerates_spelling():
    a = areas.get()
    assert [v["name"] for v in a.search("ujire")] == ["Ujre"]                    # census spelling differs
    assert [v["name"] for v in a.search("subrahmanya")] == ["Subramanya"]        # silent h
    assert [v["name"] for v in a.search("dharma")] == ["Dharmasthala"]
    assert [v["name"] for v in a.search("", taluk_id=BELTHANGADY)] == ["Dharmasthala", "Laila", "Ujre"]
    assert a.search("ujre", district="Udupi") == []


def test_find_taluk_and_district():
    a = areas.get()
    assert a.find_taluk("belthangadi")[0]["taluk_id"] == BELTHANGADY
    assert a.find_district("dakshina  kannada") == "Dakshina Kannada"
    assert a.find_taluk("nowhere") == []


def test_nearest_village():
    a = areas.get()
    assert a.nearest_village(12.991, 75.331)["name"] == "Ujre"
    assert a.nearest_village(12.79, 75.21)["name"] == "Laila"
    assert a.nearest_village(20.0, 80.0) is None                                # far outside Karnataka
