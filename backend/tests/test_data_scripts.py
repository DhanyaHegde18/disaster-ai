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
