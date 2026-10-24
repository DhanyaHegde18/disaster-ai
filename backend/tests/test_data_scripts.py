"""The data scripts (village list, grid calibration, OpenStreetMap candidates) and upgrading an old database."""
import csv
import importlib.util
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app import config, database

SCRIPTS = Path(__file__).resolve().parents[2] / "ml" / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def square(lon, lat, d=0.01):
    return [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]


def test_build_villages(tmp_path, monkeypatch):
    bv = load("build_villages")
    feats = [
        {"properties": {"NAME": "UJRE", "LOC_CODE": "1", "TALUK": "Beltangadi", "DISTRICT": "Dakshina Kannada", "T_P": 12474},
         "geometry": {"type": "Polygon", "coordinates": square(75.32, 12.98)}},
        {"properties": {"NAME": "UJRE", "LOC_CODE": "1", "TALUK": "Beltangadi", "DISTRICT": "Dakshina Kannada", "T_P": 12474},
         "geometry": {"type": "Polygon", "coordinates": square(75.40, 12.90, 0.001)}},          # small extra piece
        {"properties": {"NAME": "EMPTY", "LOC_CODE": "2", "TALUK": "Beltangadi", "DISTRICT": "Dakshina Kannada", "T_P": 0},
         "geometry": {"type": "Polygon", "coordinates": square(75.3, 12.9)}},                   # uninhabited
        {"properties": {"NAME": "KANAKAPURA", "LOC_CODE": "3", "TALUK": "Kankapura", "DISTRICT": "Bangalore Rural", "T_P": 5},
         "geometry": {"type": "MultiPolygon", "coordinates": [square(77.41, 12.54)]}},
    ]
    gj = tmp_path / "ka.geojson"
    gj.write_text(json.dumps({"features": feats}))
    monkeypatch.setattr(bv, "OUT_CSV", tmp_path / "v.csv")
    monkeypatch.setattr(bv, "OUT_AREAS", tmp_path / "a.json")
    monkeypatch.setattr("sys.argv", ["x", "--geojson", str(gj)])
    bv.main()
    rows = list(csv.DictReader(open(tmp_path / "v.csv")))
    assert sorted(r["name"] for r in rows) == ["Kanakapura", "Ujre"]
    ujre = next(r for r in rows if r["name"] == "Ujre")
    assert (ujre["taluk"], ujre["taluk_id"], ujre["district"]) == ("Belthangady", "dakshina-kannada:belthangady", "Dakshina Kannada")
    assert abs(float(ujre["lat"]) - 12.985) < 0.001 and ujre["cell_id"] == "13.00_75.25"   # biggest piece's centre
    kan = next(r for r in rows if r["name"] == "Kanakapura")
    assert kan["district"] == "Ramanagara" and kan["taluk"] == "Kanakapura"                  # newer district
    areas = json.loads((tmp_path / "a.json").read_text())
    assert {d["name"]: d["name_kn"] for d in areas["districts"]}["Ramanagara"] == "ರಾಮನಗರ"


def test_grid_thresholds_floors_and_bias(tmp_path, monkeypatch):
    bg = load("build_grid")
    days = pd.date_range("2018-01-01", "2020-12-31")
    rng = np.random.default_rng(1)
    wet = np.where(days.month.isin([6, 7, 8, 9]), rng.gamma(0.8, 40, len(days)), 0.5)     # very wet monsoon
    dry = np.where(days.month.isin([6, 7, 8, 9]), rng.gamma(0.5, 6, len(days)), 0.1)      # dry district
    daily = pd.DataFrame({"13.00_75.25": wet, "13.00_78.00": dry}, index=days)
    om = tmp_path / "om"
    om.mkdir()
    pd.DataFrame({"date": days.date, "rain_mm": wet / 2}).to_csv(om / "13.00_75.25.csv", index=False)
    monkeypatch.setattr(bg, "OM_DIR", om)
    grid, sums = bg.calibrate(daily, {"13.00_75.25": 10, "13.00_78.00": 5})
    w, d = grid["13.00_75.25"], grid["13.00_78.00"]
    assert w["past_3d"]["high"] > w["past_3d"]["medium"] > bg.FLOOR["medium"]
    assert d["past_3d"] == {"medium": 64.5, "high": 115.6}                  # floors, not the dry percentiles
    assert w["bias"]["7"] == 2.0 and d["bias"] == {}
    load_ = bg.alert_load(sums, grid)
    assert 0 < load_["high_days_per_square_per_season"] < load_["medium_or_high_days_per_square_per_season"]


def test_osm_candidates_get_a_taluk(tmp_path, monkeypatch):
    fo = load("fetch_osm_buildings")
    elements = [
        {"type": "node", "id": 1, "lat": 12.990, "lon": 75.329, "tags": {"amenity": "school", "name": "GHPS Ujre", "name:kn": "ಶಾಲೆ"}},
        {"type": "way", "id": 2, "center": {"lat": 12.80, "lon": 75.20},
         "tags": {"amenity": "community_centre", "name": "ಸಮುದಾಯ ಭವನ", "name:en": "Community Hall Laila"}},
        {"type": "node", "id": 3, "lat": 20.0, "lon": 80.0, "tags": {"amenity": "school", "name": "Far away"}},
    ]
    monkeypatch.setattr(fo, "fetch", lambda: elements)
    monkeypatch.setattr(fo, "OUT", tmp_path / "c.csv")
    monkeypatch.setattr(fo, "ROOT", tmp_path)
    fo.main()
    rows = list(csv.DictReader(open(tmp_path / "c.csv", encoding="utf-8")))
    assert [(r["shelter_id"], r["name"], r["name_kn"], r["kind"], r["taluk_id"]) for r in rows] == [
        ("osm-w2", "Community Hall Laila", "ಸಮುದಾಯ ಭವನ", "community hall", "dakshina-kannada:belthangady"),
        ("osm-n1", "GHPS Ujre", "ಶಾಲೆ", "school", "dakshina-kannada:belthangady")]


def test_old_database_is_upgraded(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, village_id TEXT NOT NULL, village_name TEXT NOT NULL,
            level TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', message_kn TEXT NOT NULL, message_en TEXT NOT NULL,
            source TEXT NOT NULL, source_note TEXT, simulated INTEGER NOT NULL DEFAULT 0, edited INTEGER NOT NULL DEFAULT 0,
            risk_json TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, review_note TEXT);
        INSERT INTO alerts (village_id, village_name, level, message_kn, message_en, source, risk_json, created_at)
            VALUES ('V001', 'Ujire', 'HIGH', 'k', 'e', 'template', '{}', '2026-08-01T09:00:00+05:30');
        CREATE TABLE officials (phone TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'gp');
        INSERT INTO officials VALUES ('+919876543210', 'Ujire GP', '2026-08-01', 'gp');
        CREATE TABLE shelters (shelter_id TEXT PRIMARY KEY, village_id TEXT NOT NULL, name TEXT NOT NULL, name_kn TEXT, kind TEXT,
            lat REAL NOT NULL, lon REAL NOT NULL, capacity INTEGER NOT NULL, phone TEXT, sample INTEGER NOT NULL DEFAULT 0,
            is_open INTEGER NOT NULL DEFAULT 0, occupancy INTEGER NOT NULL DEFAULT 0, updated_by TEXT, updated_at TEXT);
        INSERT INTO shelters (shelter_id, village_id, name, lat, lon, capacity) VALUES ('S001-1', 'V001', 'Sample school', 13.0, 75.3, 150);
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(config, "ALERTS_DB", db)
    database.init_db()
    a = database.list_alerts()[0]
    assert (a["taluk_id"], a["taluk_name"]) == ("V001", "Ujire")
    from backend.app import auth
    assert auth.get_official("+919876543210")["area"] == "All of Karnataka"
    from backend.app.services import shelters
    assert shelters.sync_from_csv()["designated"] == 0          # old sample centres removed (not in the official list)


def test_old_shelters_table_rebuilt_even_after_a_half_upgrade(tmp_path, monkeypatch):
    """The state a laptop was in: old relief-centre table (capacity required), new columns already added by a
    first start that then failed, and an OpenStreetMap candidates file present."""
    db = tmp_path / "half.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE shelters (shelter_id TEXT PRIMARY KEY, village_id TEXT NOT NULL, name TEXT NOT NULL, name_kn TEXT, kind TEXT,
            lat REAL NOT NULL, lon REAL NOT NULL, capacity INTEGER NOT NULL, phone TEXT, sample INTEGER NOT NULL DEFAULT 0,
            is_open INTEGER NOT NULL DEFAULT 0, occupancy INTEGER NOT NULL DEFAULT 0, updated_by TEXT, updated_at TEXT,
            source TEXT NOT NULL DEFAULT 'official', designated INTEGER NOT NULL DEFAULT 1, taluk_id TEXT, district TEXT, added_by TEXT);
        CREATE INDEX shelters_taluk ON shelters (taluk_id, designated);
        INSERT INTO shelters (shelter_id, village_id, name, lat, lon, capacity, source, designated, taluk_id, is_open, occupancy)
            VALUES ('gp-1', 'KA001', 'Kept hall', 12.99, 75.33, 80, 'gp', 1, 'dakshina-kannada:belthangady', 1, 12);
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(config, "ALERTS_DB", db)
    config.SHELTER_CANDIDATES_CSV.write_text(
        "shelter_id,name,name_kn,kind,lat,lon,village_id,taluk_id,district\n"
        "osm-n1,GHPS Ujre,,school,12.990,75.329,,dakshina-kannada:belthangady,Dakshina Kannada\n", encoding="utf-8")
    database.init_db()
    database.init_db()                                   # a second start changes nothing
    from backend.app.services import shelters
    assert shelters.sync_from_csv() == {"designated": 1, "candidates": 1}
    kept = shelters.get("gp-1")
    assert (kept["name"], kept["is_open"], kept["occupancy"]) == ("Kept hall", True, 12)
    assert shelters.get("osm-n1")["capacity"] == 0
    with database.connect() as cx:
        assert cx.execute("SELECT name FROM sqlite_master WHERE name = 'shelters_taluk'").fetchone()


def test_fetch_landslides_reads_the_nasa_export(tmp_path, monkeypatch):
    fl = load("fetch_landslides")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "nasa.csv").write_text(
        "event_date,event_title,location_accuracy,landslide_category,landslide_trigger,country_name,longitude,latitude\n"
        "08/16/2018 12:00:00 AM,Slide near Ujre,5km,landslide,downpour,India,75.331,12.991\n"
        "08/16/2018 03:00:00 PM,Same slide again,1km,landslide,rain,India,75.300,12.950\n"     # same square, same day
        "2018-08-17,Vague one,50km,landslide,downpour,India,75.33,12.99\n"
        "2018-08-18,Quake slide,5km,landslide,earthquake,India,75.33,12.99\n"
        "2018-08-19,Far away,5km,landslide,rain,India,77.0,28.6\n"
        "2019-08-09,Laila slide,10km,mudslide,monsoon,India,75.201,12.801\n", encoding="utf-8")
    monkeypatch.setattr(fl, "IN_DIR", raw)
    monkeypatch.setattr(fl, "OUT", tmp_path / "out.csv")
    monkeypatch.setattr(fl, "ROOT", tmp_path)                    # no events.csv here
    monkeypatch.setattr("sys.argv", ["fetch_landslides.py"])
    fl.main()
    rows = list(csv.DictReader(open(tmp_path / "out.csv", encoding="utf-8")))
    assert [(r["date"], r["cell_id"]) for r in rows] == [("2018-08-16", "13.00_75.25"), ("2019-08-09", "12.75_75.25")]


def test_training_runs_and_saves_a_usable_model(tmp_path, world):
    tl = load_training("train_landslide")
    rng = np.random.default_rng(1)
    cells = ["13.00_75.25", "12.75_75.25", "12.75_75.50", "13.25_74.75"] + [f"14.{i:02d}_76.00" for i in range(8)]
    days = pd.date_range("2016-01-01", "2018-12-31")
    season = np.exp(-((days.dayofyear.values - 200) / 50.0) ** 2)
    daily = pd.DataFrame({c: rng.gamma(0.7, 30, len(days)) * season for c in cells}, index=days)
    slopes = [35, 30, 38, 4] + [3 + i for i in range(8)]
    terrain = pd.DataFrame({"slope_p90": slopes, "steep_share": [s / 80 for s in slopes], "relief": [s * 30 for s in slopes]}, index=cells)
    ev = []
    for c, sl in zip(cells, slopes):
        s = daily[c]
        risk = (sl / 35) ** 3 * (s.rolling(15).sum() / 250) * ((s.shift(-1) + s.shift(-2) + s.shift(-3)) / 100)
        ev += [{"date": (d + pd.Timedelta(days=2)).date().isoformat(), "cell_id": c} for d in days[risk.fillna(0) > 0.8]][::3]
    events = pd.DataFrame(ev).drop_duplicates()
    grid = {"cells": {c: {"past_3d": {"medium": 100, "high": 150}, "forecast_3d": {"medium": 100, "high": 150}} for c in cells}}
    t = tl.build_table(daily, terrain, events)
    meta = tl.train_and_save(t, terrain, grid, events, tmp_path / "m.joblib", tmp_path / "m.json", tmp_path / "r.md")
    assert set(meta["metrics"]) >= {"rule", meta["model"]}
    assert meta["metrics"][meta["model"]]["PR-AUC"] > meta["metrics"]["rule"]["PR-AUC"]      # slope matters; the rule ignores it
    assert 0 < meta["thresholds"]["medium"] < meta["thresholds"]["high"] < 1
    assert "caught @ 2% budget" in (tmp_path / "r.md").read_text()
    from backend.app.services import landslide
    landslide.MODEL_FILE.write_bytes((tmp_path / "m.joblib").read_bytes())
    landslide.META_FILE.write_text((tmp_path / "m.json").read_text())
    p = landslide.predict_cells({"12.75_75.50": landslide.rain_features([30.0] * 15, [60.0, 60.0, 60.0]),
                                 "13.25_74.75": landslide.rain_features([30.0] * 15, [60.0, 60.0, 60.0])})
    assert p["12.75_75.50"]["prob"] > p["13.25_74.75"]["prob"]                               # steep beats flat


def load_training(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS.parent / "training" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_slope_from_elevation_tiles(tmp_path):
    import math
    import pytest
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    ft = load("fetch_cell_terrain")
    n, res = 300, 1 / 1200
    xx = np.mgrid[0:n, 0:n][1]
    ramp = (xx * res * 111320 * math.tan(math.radians(30))).astype("float32") + 10
    path = tmp_path / "t.tif"
    with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(75.375, 12.625, res, res)) as f:
        f.write(ramp, 1)
    with rasterio.open(path) as ds:
        z, rx, ry = ft.read_square([ds], 12.5, 75.5)
    s = ft.stats(z, rx, ry, 12.5)
    assert 29.5 < s["slope_p90"] < 31.5 and s["steep_share"] > 0.95       # 30 deg ramp (a bit more after cos(lat))
    assert ft.stats(np.full((60, 60), 50.0), res, res, 12.5)["slope_p90"] == 0.0
    assert ft.stats(np.zeros((60, 60)), res, res, 12.5) == {"slope_p90": 0.0, "steep_share": 0.0, "relief": 0.0, "elev_mean": 0.0}
    assert ft.tile_name(12, 75) == "Copernicus_DSM_COG_30_N12_00_E075_00_DEM"


def test_fetch_landslides_auto_download(tmp_path, monkeypatch):
    fl = load("fetch_landslides")

    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    pages = {"offset0": {"features": [
                {"attributes": {"event_date": 1534377600000, "event_title": "Slide near Ujre", "location_accuracy": "5km",
                                "landslide_trigger": "downpour"}, "geometry": {"x": 75.331, "y": 12.991}},
                {"attributes": {"title": "Manual, Laila, 2019-08-09", "method": "Manual"}, "geometry": {"x": 75.201, "y": 12.801}}],
             "exceededTransferLimit": True},
             "offset2": {"features": [], "exceededTransferLimit": False}}

    class Session:
        headers = {}
        def get(self, url, params, timeout):
            if url.endswith("/Landslides"):
                return Resp({"services": [{"name": "Landslides/COOLR_Reports_Points", "type": "MapServer"}]})
            if url.endswith("/MapServer"):
                return Resp({"layers": [{"id": 0, "name": "reports", "geometryType": "esriGeometryPoint"}]})
            if url.endswith("/query"):
                return Resp(pages[f"offset{params['resultOffset']}"])
            return Resp({"error": "nope"})

    import requests
    monkeypatch.setattr(requests, "Session", Session)
    raw = tmp_path / "raw"
    monkeypatch.setattr(fl, "IN_DIR", raw)
    monkeypatch.setattr(fl, "OUT", tmp_path / "out.csv")
    monkeypatch.setattr(fl, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["x", "--auto"])
    fl.main()
    assert list(raw.glob("auto_*.csv"))
    rows = list(csv.DictReader(open(tmp_path / "out.csv", encoding="utf-8")))
    assert [(r["date"], r["cell_id"]) for r in rows] == [("2018-08-16", "13.00_75.25"), ("2019-08-09", "12.75_75.25")]
