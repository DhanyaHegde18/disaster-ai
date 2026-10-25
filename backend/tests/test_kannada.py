"""Kannada names: romanizing for comparison, loading name files, Kannada search, and the names script."""
import csv
import os
import time

from backend.app import areas, config, kannada
from backend.app.services import alert_drafter, risk_view
from backend.tests.conftest import BELTHANGADY, app_client
from backend.tests.test_data_scripts import load


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    # make sure the file looks changed even within the same second (the loader watches modification times)
    os.utime(path, (time.time() + 1, time.time() + 1)) if path.exists() else None


def test_romanize():
    assert kannada.romanize("ಬೆಳ್ತಂಗಡಿ") == "beltangadi"
    assert kannada.romanize("ಉಜಿರೆ") == "ujire"
    assert kannada.romanize("ಸುಬ್ರಹ್ಮಣ್ಯ") == "subrahmanya"
    assert kannada.romanize("ಹೊಸಹಳ್ಳಿ") == "hosahalli"
    assert kannada.romanize("ಮಂಗಳೂರು") == "mangalooru"
    assert kannada.clean(" ಉಜಿ‌ರೆ   ") == "ಉಜಿರೆ"


def test_sounds_like_census_spellings():
    assert kannada.sounds_like("ಉಜಿರೆ", "Ujre") == 1.0
    assert kannada.sounds_like("ಬೆಳ್ತಂಗಡಿ", "Belthangady") == 1.0
    assert kannada.sounds_like("ಲಕ್ಷ್ಮೀವಾಡಿ", "Laxmiwadi") == 1.0
    assert kannada.sounds_like("ಧರ್ಮಸ್ಥಳ", "Ujre") < 0.4
    assert kannada.sounds_like("ಉಜಿರೆ", "") == 0.0


def test_names_files_are_merged_and_fixes_win():
    write(config.VILLAGE_NAMES_KN_CSV, ["village_id", "name_kn", "source", "score"],
          [["KA001", "ಉಜಿರೆ", "osm", "1.0"], ["KA003", "ಲೈಲಾ", "ai", "0.8"], ["KA004", "not kannada", "ai", "1"]])
    write(config.TALUK_NAMES_KN_CSV, ["taluk_id", "name_kn", "source", "score"], [[BELTHANGADY, "ಬೆಳ್ತಂಗಡಿ", "ai", "1"]])
    write(config.NAME_KN_FIXES_CSV, ["id", "name_kn"], [["KA003", "ಲಾಯಿಲ"]])
    a = areas.get()
    assert (a.village("KA001")["name_kn"], a.village("KA001")["name_kn_source"]) == ("ಉಜಿರೆ", "osm")
    assert (a.village("KA003")["name_kn"], a.village("KA003")["name_kn_source"]) == ("ಲಾಯಿಲ", "fix")
    assert a.village("KA004")["name_kn"] is None                     # Latin text is never taken as Kannada
    assert a.taluk(BELTHANGADY)["name_kn"] == "ಬೆಳ್ತಂಗಡಿ"
    dk = next(d for d in a.districts if d["name"] == "Dakshina Kannada")
    assert {t["name_kn"] for t in dk["taluks"]} == {"ಬೆಳ್ತಂಗಡಿ", None}


def test_reloads_when_names_file_changes():
    assert areas.get().village("KA001")["name_kn"] is None
    write(config.VILLAGE_NAMES_KN_CSV, ["village_id", "name_kn", "source", "score"], [["KA001", "ಉಜಿರೆ", "osm", "1"]])
    assert areas.get().village("KA001")["name_kn"] == "ಉಜಿರೆ"


def test_search_in_kannada():
    write(config.VILLAGE_NAMES_KN_CSV, ["village_id", "name_kn", "source", "score"], [["KA001", "ಉಜಿರೆ", "osm", "1"]])
    a = areas.get()
    assert [v["name"] for v in a.search("ಉಜಿ")] == ["Ujre"]                 # stored Kannada name
    assert [v["name"] for v in a.search("ಧರ್ಮಸ್ಥಳ")] == ["Dharmasthala"]    # no Kannada name: by sound
    assert [v["name"] for v in a.search("ಸುಬ್ರಹ್ಮಣ್ಯ")] == ["Subramanya"]
    assert a.search("ಮೈಸೂರು") == []
    assert [v["name"] for v in a.search("ujire")] == ["Ujre"]               # English still works


def test_public_api_shows_kannada_names():
    write(config.VILLAGE_NAMES_KN_CSV, ["village_id", "name_kn", "source", "score"], [["KA001", "ಉಜಿರೆ", "osm", "1"]])
    write(config.TALUK_NAMES_KN_CSV, ["taluk_id", "name_kn", "source", "score"], [[BELTHANGADY, "ಬೆಳ್ತಂಗಡಿ", "ai", "1"]])
    c = app_client()
    v = c.get("/public/village/KA001").json()
    assert (v["name_kn"], v["taluk_kn"], v["district_kn"], v["name_kn_source"]) == ("ಉಜಿರೆ", "ಬೆಳ್ತಂಗಡಿ", "ದಕ್ಷಿಣ ಕನ್ನಡ", "osm")
    found = c.get("/public/villages", params={"q": "ಉಜಿರೆ"}).json()
    assert [f["village_id"] for f in found] == ["KA001"]


def test_alert_template_uses_kannada_names(world):
    write(config.VILLAGE_NAMES_KN_CSV, ["village_id", "name_kn", "source", "score"],
          [["KA001", "ಉಜಿರೆ", "osm", "1"], ["KA002", "ಧರ್ಮಸ್ಥಳ", "osm", "1"]])
    write(config.TALUK_NAMES_KN_CSV, ["taluk_id", "name_kn", "source", "score"], [[BELTHANGADY, "ಬೆಳ್ತಂಗಡಿ", "ai", "1"]])
    world.rain("13.00_75.25", past=200)
    from backend.app.jobs.score_grid import score_now
    r = risk_view.taluk_risk(score_now(), BELTHANGADY)
    d = alert_drafter.draft_alert(r)
    assert "ಬೆಳ್ತಂಗಡಿ ತಾಲ್ಲೂಕಿನಲ್ಲಿ" in d["kn"] and "ಉಜಿರೆ, ಧರ್ಮಸ್ಥಳ" in d["kn"]
    assert "Belthangady taluk" in d["en"] and "Ujre" in d["en"]


# ---------- ml/scripts/fetch_kannada_names.py ----------

def village(vid, name, lat, lon):
    return {"village_id": vid, "name": name, "lat": lat, "lon": lon}


def test_osm_match_needs_nearby_and_same_sound():
    fk = load("fetch_kannada_names")
    vs = [village("1", "Ujre", 12.99, 75.33), village("2", "Laila", 12.80, 75.20), village("3", "Kokkada", 12.90, 75.40)]
    places = [
        {"lat": 12.995, "lon": 75.335, "kn": "ಉಜಿರೆ", "place": "village", "name": "Ujire"},        # 0.7 km: yes
        {"lat": 12.801, "lon": 75.201, "kn": "ಧರ್ಮಸ್ಥಳ", "place": "village", "name": None},        # close, other name
        {"lat": 12.80, "lon": 75.30, "kn": "ಲಾಯಿಲ", "place": "village", "name": "Laila"},          # right name, 11 km
    ]
    assert fk.match_osm(vs, places) == {"1": ("ಉಜಿರೆ", 1.0)}


def test_ai_answers_are_checked_and_saved(monkeypatch, tmp_path):
    fk = load("fetch_kannada_names")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(fk, "DROPPED", tmp_path / "dropped.csv")
    asked = []

    def fake(items):
        asked.append([i["id"] for i in items])
        return [{"id": "KA001", "kn": "ಉಜಿರೆ"}, {"id": "KA002", "kn": "Dharmasthala"},     # Latin: dropped
                {"id": "KA003", "kn": "ಮೈಸೂರು"}, {"id": "nope", "kn": "ಉಜಿರೆ"},            # wrong word / unknown id
                {"id": BELTHANGADY, "kn": "ಬೆಳ್ತಂಗಡಿ"}]
    monkeypatch.setattr(fk, "ask_gemini", fake)
    todo = [{"id": BELTHANGADY, "name": "Belthangady", "kind": "taluk", "taluk": "Belthangady", "district": "DK"}] + [
        {"id": i, "name": n, "kind": "village", "taluk": "Belthangady", "district": "DK"}
        for i, n in (("KA001", "Ujre"), ("KA002", "Dharmasthala"), ("KA003", "Laila"))]
    v_out, t_out = {}, {}
    fk.run_ai(todo, v_out, t_out, pause=0)
    assert set(v_out) == {"KA001"} and set(t_out) == {BELTHANGADY}
    assert fk.load(config.VILLAGE_NAMES_KN_CSV, "village_id")["KA001"]["source"] == "ai"
    assert areas.get().village("KA001")["name_kn"] == "ಉಜಿರೆ"
    with open(tmp_path / "dropped.csv", encoding="utf-8") as f:
        why = {r["id"]: r["why"] for r in csv.DictReader(f)}
    assert why["KA002"] == "not Kannada script" and why["KA003"].startswith("sounds different")


def test_ai_stops_cleanly_when_quota_is_used_up(monkeypatch, capsys, tmp_path):
    fk = load("fetch_kannada_names")
    monkeypatch.setattr(fk, "DROPPED", tmp_path / "dropped.csv")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(fk, "BATCH", 1)

    def fake(items):
        if items[0]["id"] == "KA002":
            raise RuntimeError("gemini HTTP 429: quota exceeded")
        return [{"id": items[0]["id"], "kn": "ಉಜಿರೆ"}]
    monkeypatch.setattr(fk, "ask_gemini", fake)
    todo = [{"id": i, "name": "Ujre", "kind": "village", "taluk": "B", "district": "DK"} for i in ("KA001", "KA002", "KA003")]
    v_out = {}
    fk.run_ai(todo, v_out, {}, pause=0)
    assert set(v_out) == {"KA001"}                                    # kept what it had, stopped at the error
    assert "Run again tomorrow" in capsys.readouterr().out


def test_census_codes_ignored_when_checking():
    fk = load("fetch_kannada_names")
    assert fk.core("Mangalore Mc") == "Mangalore" and fk.core("Kadur Tmc") == "Kadur" and fk.core("Mc") == "Mc"
    assert fk.valid("ಕಡೂರು", "Kadur Tmc", fk.AI_MIN)
    assert fk.valid("ಬೆಳ್ತಂಗಡಿ", "Kadur Tmc", fk.AI_MIN) is None


def test_osm_places_need_position_and_kannada_name():
    fk = load("fetch_kannada_names")
    assert "out body" in fk.QUERY                                     # "out tags" would drop the positions
    got = fk.parse_places([
        {"lat": 12.98, "lon": 75.33, "tags": {"place": "village", "name": "Ujire", "name:kn": "ಉಜಿರೆ"}},
        {"lat": 12.95, "lon": 75.30, "tags": {"place": "village", "name": "ಧರ್ಮಸ್ಥಳ"}},
        {"lat": 12.90, "lon": 75.20, "tags": {"place": "village", "name": "Laila"}},           # no Kannada name
        {"tags": {"place": "village", "name:kn": "ಕೊಕ್ಕಡ"}},                                   # no position
    ])
    assert [(p["kn"], p["name"]) for p in got] == [("ಉಜಿರೆ", "Ujire"), ("ಧರ್ಮಸ್ಥಳ", "ಧರ್ಮಸ್ಥಳ")]


def test_eval_compares_ai_with_osm(tmp_path, monkeypatch):
    fk = load("fetch_kannada_names")
    sample = [{"village_id": "1", "name": "Ujre", "taluk": "B", "district": "DK", "osm": "ಉಜಿರೆ"},
              {"village_id": "2", "name": "Hubli Dharwad", "taluk": "H", "district": "D", "osm": "ಹುಬ್ಬಳ್ಳಿ-ಧಾರವಾಡ"},
              {"village_id": "3", "name": "Belal", "taluk": "B", "district": "DK", "osm": "ಬೆಳಾಲು"},
              {"village_id": "4", "name": "Laila", "taluk": "B", "district": "DK", "osm": "ಲಾಯಿಲ"}]
    answers = {"1": "ಉಜಿರೆ", "2": "ಹುಬ್ಬಳ್ಳಿ ಧಾರವಾಡ", "3": "ಬೆಲಾಲು", "4": "ಮೈಸೂರು"}
    res = fk.evaluate(sample, answers)
    assert (res["exact"], res["letters"], res["passed"]) == (0.25, 0.5, 0.75)
    assert res["passed_and_same"] == 2 / 3 and res["refused_but_same"] == 0
    assert [r["village_id"] for r in res["differences"]] == ["3", "4"]
    monkeypatch.setattr(fk, "REPORT", tmp_path / "r.md")
    fk.write_eval(res, "test-model")
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "**50%**" in text and "| Belal | B | ಬೆಳಾಲು | ಬೆಲಾಲು | yes |" in text


def test_local_examples_for_a_batch():
    fk = load("fetch_kannada_names")
    by_taluk = {"t1": [{"id": str(i), "name": n, "taluk": "T1", "kn": "ಕ"} for i, n in
                       enumerate(["Hosahalli", "Kodihalli", "Belal", "Ujre", "Kokkada"])],
                "t2": [{"id": "x", "name": "Laila", "taluk": "T2", "kn": "ಲಾಯಿಲ"}]}
    batch = [{"id": "q", "name": "Doddahalli", "taluk_id": "t1"}]
    got = fk.examples_for(batch, by_taluk, exclude={"1"})
    assert [e["name"] for e in got][:1] == ["Hosahalli"]               # same ending first; Kodihalli is hidden
    assert "Kodihalli" not in [e["name"] for e in got] and len(got) == 4
    assert all(e["taluk"] == "T1" for e in got)                       # only the batch's own taluks
    p = fk.prompt_for([{"id": "q", "name": "Doddahalli", "kind": "village", "taluk": "T1", "district": "D"}], got)
    assert "Hosahalli (T1) -> ಕ" in p and fk.prompt_for(batch and [], None).count("OpenStreetMap") == 0


def test_respell_marks_names_spelled_with_examples(monkeypatch, tmp_path):
    fk = load("fetch_kannada_names")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(fk, "DROPPED", tmp_path / "dropped.csv")
    seen = []
    monkeypatch.setattr(fk, "ask_gemini", lambda items, examples=None: seen.append(examples) or
                        [{"id": "KA001", "kn": "ಉಜಿರೆ"}, {"id": "KA003", "kn": "ಮೈಸೂರು"}])
    v_out = {"KA001": {"village_id": "KA001", "name_kn": "ಉಜ್ರೆ", "source": "ai", "score": 1},
             "KA003": {"village_id": "KA003", "name_kn": "ಲೈಲಾ", "source": "ai", "score": 1}}
    todo = [{"id": "KA001", "name": "Ujre", "kind": "village", "taluk": "B", "taluk_id": BELTHANGADY, "district": "DK"},
            {"id": "KA003", "name": "Laila", "kind": "village", "taluk": "B", "taluk_id": BELTHANGADY, "district": "DK"}]
    fk.run_ai(todo, v_out, {}, 0, {BELTHANGADY: [{"id": "KA002", "name": "Dharmasthala", "taluk": "B", "kn": "ಧರ್ಮಸ್ಥಳ"}]})
    assert v_out["KA001"]["name_kn"] == "ಉಜಿರೆ" and v_out["KA001"]["source"] == "ai-local"
    assert v_out["KA003"] == {"village_id": "KA003", "name_kn": "ಲೈಲಾ", "source": "ai", "score": 1}   # refused: kept
    assert seen[0][0]["name"] == "Dharmasthala"


def test_slow_batches_are_split(monkeypatch, capsys):
    fk = load("fetch_kannada_names")
    sizes = []

    def fake(items, examples=None):
        sizes.append(len(items))
        if len(items) > 25:
            raise RuntimeError("gemini-3.8-flash HTTP 0: no answer within 180s (ReadTimeout)")
        return [{"id": i["id"], "kn": "ಉಜಿರೆ"} for i in items]
    monkeypatch.setattr(fk, "ask_gemini", fake)
    got = fk.ask_in_parts([{"id": str(i), "name": "Ujre"} for i in range(100)])
    assert len(got) == 100 and sizes == [100, 50, 25, 25, 50, 25, 25]
    monkeypatch.setattr(fk, "ask_gemini", lambda items, examples=None: (_ for _ in ()).throw(RuntimeError("HTTP 429 quota")))
    import pytest
    with pytest.raises(RuntimeError, match="429"):                    # quota errors are not split, they stop the run
        fk.ask_in_parts([{"id": "1", "name": "Ujre"}] * 40)


def test_find_names_in_any_envelope():
    fk = load("fetch_kannada_names")
    assert fk.find_names({"outputs": [{"text": '```json\n{"names": [{"id": "1", "kn": "ಉಜಿರೆ"}]}\n```'}]}) == \
        [{"id": "1", "kn": "ಉಜಿರೆ"}]
    assert fk.find_names({"outputs": []}) is None
