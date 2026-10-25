"""River floods: building flood levels from GloFAS history, and the live check raising squares near a rising river."""
import datetime as dt
import json

import pytest

from backend.app import areas, config
from backend.app.jobs import score_grid
from backend.app.services import alert_drafter, risk_view, rivers
from backend.tests.conftest import BELTHANGADY, SULLIA, app_client, sign_in
from backend.tests.test_data_scripts import load

LAILA_CELL = "12.75_75.25"     # Laila (Belthangady); Sullia's only square is 12.75_75.50


def river_cfg(medium=1000.0, high=2000.0):
    return {"created": "2026-10-25", "source": "test", "years": list(range(2005, 2023)), "points": {
        "netravati-test": {"river": "Netravati", "river_kn": "ನೇತ್ರಾವತಿ", "place": "Laila", "lat": 12.80, "lon": 75.20,
                           "radius_km": 5, "medium": medium, "high": high, "record": 3000.0, "top_years": [2019],
                           "years": 18, "villages": 1, "taluk_ids": [BELTHANGADY], "cells": [LAILA_CELL],
                           "places": ["Laila"]}}}


@pytest.fixture
def river(monkeypatch):
    """A river point near Laila, and a settable forecast: river.flow = peak m3/s tomorrow."""
    config.RIVER_CONFIG.write_text(json.dumps(river_cfg(), ensure_ascii=False), encoding="utf-8")

    class Flow:
        peak = 300.0
        fail = False
        asked = None
    flow = Flow()

    def fake(points):
        flow.asked = points
        if flow.fail:
            raise RuntimeError("Open-Meteo flood API unavailable after 3 tries: 503")
        today = dt.date.today()
        return {pid: [(today + dt.timedelta(days=i), flow.peak if i == 1 else 200.0) for i in range(-1, 6)]
                for pid in points}
    monkeypatch.setattr(rivers, "fetch_discharge", fake)
    return flow


def cell(snap, cid):
    return next(c for c in snap["cells"] if c["cell_id"] == cid)


def test_no_river_config_changes_nothing():
    snap = score_grid.score_now()
    assert snap["rivers"] == [] and "rivers" not in snap["engine"]


def test_high_river_raises_its_square_alone(river):
    river.peak = 2500.0
    snap = score_grid.score_now()
    c = cell(snap, LAILA_CELL)
    assert c["level"] == "HIGH" and c["level_cause"] == "river" and c["rivers"] == ["netravati-test"]
    assert any(r.startswith("Netravati river at Laila: up to 2,500 m³/s") for r in c["reasons"])
    assert "Rainfall below warning thresholds" not in c["reasons"]
    assert cell(snap, "13.00_75.25")["level"] == "LOW"                   # other squares untouched
    assert snap["rivers"][0]["level"] == "HIGH" and snap["engine"].endswith("+ rivers")
    assert river.asked == {"netravati-test": (12.80, 75.20)}


def test_medium_river_and_low_river(river):
    river.peak = 1500.0
    assert cell(score_grid.score_now(), LAILA_CELL)["level"] == "MEDIUM"
    river.peak = 900.0
    c = cell(score_grid.score_now(), LAILA_CELL)
    assert c["level"] == "LOW" and "rivers" not in c


def test_river_never_lowers_a_wet_square(river, world):
    world.rain(LAILA_CELL, past=200)
    river.peak = 1500.0
    c = cell(score_grid.score_now(), LAILA_CELL)
    assert c["level"] == "HIGH" and "level_cause" not in c                # rain made it HIGH; river is a 2nd reason
    assert len(c["reasons"]) == 2


def test_river_service_down_keeps_rain_warnings(river, world):
    world.rain("13.00_75.25", past=200)
    river.fail = True
    snap = score_grid.score_now()
    assert snap["rivers"] == [] and "503" in snap["rivers_error"]
    assert cell(snap, "13.00_75.25")["level"] == "HIGH"


def test_taluk_view_and_alert_name_the_river(river):
    river.peak = 2500.0
    snap = score_grid.score_now()
    r = risk_view.taluk_risk(snap, BELTHANGADY)
    assert r["level"] == "HIGH" and r["cause"] == "river"
    assert [x["river"] for x in r["rivers"]] == ["Netravati"]
    assert risk_view.taluk_risk(snap, SULLIA)["rivers"] == []
    f = alert_drafter.facts_for(r)
    assert f["main_cause"] == "river" and f["rivers_rising"] == ["Netravati"] and f["rivers_rising_kn"] == ["ನೇತ್ರಾವತಿ"]
    d = alert_drafter.draft_alert(r)
    assert "Netravati river may rise to flood level" in d["en"] and " mm " not in d["en"]
    assert "ನೇತ್ರಾವತಿ ನದಿಯ ನೀರು ಪ್ರವಾಹದ ಮಟ್ಟಕ್ಕೆ" in d["kn"] and "  " not in d["kn"]
    assert alert_drafter.check_draft(d, f) == []


def test_rain_alert_mentions_river_too(river, world):
    world.rain(LAILA_CELL, past=60, future=200)
    river.peak = 1500.0
    r = risk_view.taluk_risk(score_grid.score_now(), BELTHANGADY)
    d = alert_drafter.draft_alert(r)
    assert "Netravati river may rise" in d["en"] and "200 mm of rain is expected" in d["en"]


def test_dashboard_scope_and_health(river):
    river.peak = 2500.0
    with app_client() as gp, app_client() as other:
        sign_in(gp, taluk_id=BELTHANGADY)
        assert [x["point_id"] for x in gp.get("/risk").json()["rivers"]] == ["netravati-test"]
        sign_in(other, "Sullia GP", "9123400000", taluk_id=SULLIA)
        assert other.get("/risk").json()["rivers"] == []
        assert gp.get("/health").json()["rivers"].startswith("1 river points, flood levels from GloFAS 2005-2022")


# ---------- ml/scripts/build_rivers.py ----------

def test_flood_levels_from_yearly_peaks():
    br = load("build_rivers")
    peaks = {2005 + i: float(v) for i, v in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])}
    lv = br.flood_levels(peaks)
    assert lv["medium"] == 550.0 and lv["high"] == 820.0 and lv["record"] == 1000.0
    assert lv["top_years"] == [2014, 2013, 2012] and lv["years"] == 10


def test_affected_villages_within_radius():
    br = load("build_rivers")
    got = br.affected(areas.get(), {"lat": 12.99, "lon": 75.33, "radius_km": 3})
    assert got["villages"] == 1 and got["taluk_ids"] == [BELTHANGADY] and got["cells"] == ["13.00_75.25"]
    assert br.affected(areas.get(), {"lat": 12.99, "lon": 75.33, "radius_km": 8})["places"] == ["Ujre", "Dharmasthala"]


def test_fetch_year_uses_cache(tmp_path, monkeypatch):
    br = load("build_rivers")
    monkeypatch.setattr(br, "CACHE", tmp_path / "glofas")
    calls = []

    class Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return [{"daily": {"river_discharge": [1.0, 5.0, None]}}, {"daily": {"river_discharge": [2.0, 3.0]}}]

    def fake_get(url, params, timeout):
        calls.append(params)
        return Resp()
    monkeypatch.setattr(br.requests, "get", fake_get)
    pts = [{"point_id": "a", "lat": 1.0, "lon": 2.0}, {"point_id": "b", "lat": 3.0, "lon": 4.0}]
    assert br.fetch_year(pts, 2019) == {"a": [1.0, 5.0], "b": [2.0, 3.0]}
    assert calls[0]["start_date"] == "2019-06-01" and calls[0]["latitude"] == "1.0,3.0"
    assert br.fetch_year(pts, 2019) == {"a": [1.0, 5.0], "b": [2.0, 3.0]} and len(calls) == 1   # from the cache


def test_river_points_file_is_valid():
    br = load("build_rivers")
    pts = br.read_points()
    assert len(pts) >= 20 and len({p["point_id"] for p in pts}) == len(pts)
    assert all(11.5 < p["lat"] < 18.5 and 74 < p["lon"] < 78.6 and p["river_kn"] for p in pts)


def test_snap_moves_point_onto_biggest_river(tmp_path, monkeypatch):
    br = load("build_rivers")
    monkeypatch.setattr(br, "SNAP_FILE", tmp_path / "snap.json")
    monkeypatch.setattr(br.time, "sleep", lambda s: None)
    calls = []

    def fake_get(params, label):
        calls.append(label)
        lats = [float(x) for x in params["latitude"].split(",")]
        lons = [float(x) for x in params["longitude"].split(",")]
        assert len(lats) == 25
        # the "river" is one cell north-east of the point: 5000 m3/s there, a stream (3) everywhere else
        return [{"daily": {"river_discharge": [5000.0 if (abs(la - 16.26) < 1e-6 and abs(lo - 76.40) < 1e-6) else 3.0]}}
                for la, lo in zip(lats, lons)]
    monkeypatch.setattr(br, "_get", fake_get)
    pts = [{"point_id": "krishna-narayanpur", "lat": 16.21, "lon": 76.35}]
    got = br.snap(pts)["krishna-narayanpur"]
    assert (got["lat"], got["lon"], got["mean"], got["mean_before"]) == (16.26, 76.40, 5000.0, 3.0)
    assert 7 < got["moved_km"] < 8
    br.snap(pts)
    assert len(calls) == 1                                            # cached


def test_moved_point_is_fetched_again_old_cache_kept(tmp_path, monkeypatch):
    br = load("build_rivers")
    monkeypatch.setattr(br, "CACHE", tmp_path)
    (tmp_path / "2019.json").write_text(json.dumps({"a": [1.0, 9.0], "b": [2.0, 3.0]}))   # old format, csv positions
    asked = []

    def fake_get(params, label):
        asked.append(params["latitude"])
        return [{"daily": {"river_discharge": [500.0, 800.0]}}]
    monkeypatch.setattr(br, "_get", fake_get)
    pts = [{"point_id": "a", "lat": 1.0, "lon": 2.0, "csv_lat": 1.0, "csv_lon": 2.0},
           {"point_id": "b", "lat": 3.05, "lon": 4.0, "csv_lat": 3.0, "csv_lon": 4.0}]           # b was moved
    assert br.fetch_year(pts, 2019) == {"a": [1.0, 9.0], "b": [500.0, 800.0]}
    assert asked == ["3.05"]                                          # only the moved point downloaded
    assert br.fetch_year(pts, 2019)["b"] == [500.0, 800.0] and len(asked) == 1


def test_report_flags_small_streams(tmp_path, monkeypatch):
    br = load("build_rivers")
    monkeypatch.setattr(br, "REPORT", tmp_path / "rivers.md")
    base = {"river_kn": "x", "lat": 1, "lon": 2, "radius_km": 8, "years": 18, "villages": 3, "medium": 1, "high": 2}
    cfg = {"created": "2026-10-25", "years": list(range(2005, 2023)), "points": {
        "big": {**base, "river": "Krishna", "place": "Almatti", "record": 13212, "top_years": [2019, 2020, 2008], "moved_km": 0},
        "tiny": {**base, "river": "Bhima", "place": "Yadgir", "record": 38, "top_years": [2020, 2007, 2009], "moved_km": 5.6}}}
    br.write_report(cfg)
    text = (tmp_path / "rivers.md").read_text(encoding="utf-8")
    assert "**1 of 2 points**" in text and "| 38 ⚠ small |" in text and "| 5.6 km |" in text


def test_small_stream_points_are_not_used(river):
    cfg = river_cfg()
    cfg["points"]["stream"] = {**cfg["points"]["netravati-test"], "small": True, "place": "Stream"}
    config.RIVER_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    river.peak = 2500.0
    snap = score_grid.score_now()
    assert [r["point_id"] for r in snap["rivers"]] == ["netravati-test"] and "stream" not in river.asked
    with app_client() as c:
        assert c.get("/health").json()["rivers"].startswith("1 river points")


def test_choose_stays_near_town_on_the_main_river():
    br = load("build_rivers")
    town = (16.00, 76.00)
    cands = [(16.00, 76.00), (16.00, 76.05), (16.00, 76.10), (16.05, 76.00)]
    # on the river already (2,538 vs 2,579 downstream): stays
    assert br.choose(town, cands, [2538.0, 2560.0, 2579.0, 3.0]) == 0
    # on a stream (3) next to the river: moves to the nearest river cell, not the farthest/biggest one
    assert br.choose(town, cands, [3.0, 3500.0, 3710.0, 2.0]) == 1


def test_snap_reuses_cached_flows_without_calls(tmp_path, monkeypatch):
    br = load("build_rivers")
    monkeypatch.setattr(br, "SNAP_FILE", tmp_path / "snap.json")
    monkeypatch.setattr(br.time, "sleep", lambda s: None)
    means = [3.0] * 25
    means[13] = 4000.0                                               # one cell east of the centre
    (tmp_path / "snap.json").write_text(json.dumps({"x": {"from": "16.0000,76.0000", "means": means}}))
    monkeypatch.setattr(br, "_get", lambda params, label: (_ for _ in ()).throw(AssertionError("no calls")))
    got = br.snap([{"point_id": "x", "lat": 16.0, "lon": 76.0}])["x"]
    assert (got["lat"], got["lon"], got["mean"]) == (16.0, 76.05, 4000.0)
