"""
Relief centres (ಕಾಳಜಿ ಕೇಂದ್ರ), real ones only, plus possible ones for staff to choose from.

  ml/data/shelters.csv            official lists you collect (e.g. from district disaster plans): designated
  ml/data/shelter_candidates.csv  schools / community halls / GP offices from OpenStreetMap
                                  (ml/scripts/fetch_osm_buildings.py): NOT shown to villagers until a
                                  Gram Panchayat official designates one and gives its capacity
  dashboard                       a GP official can also add a centre by clicking the map

At start-up the table is refreshed from the two files (only when a file has changed).
Open/closed, head counts, and which candidates were designated are always kept.
"""
import csv
import hashlib
import math
import secrets

from .. import areas, config, database

STATIC = ("name", "name_kn", "kind", "lat", "lon")
REACHABLE_KM = 15        # an open centre farther than this is not a sensible place to send people in a flood


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("shelter_id") or "").strip()]


def _file_hash(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def _place(lat: float, lon: float, taluk_id: str | None = None) -> tuple[str | None, str | None, str | None]:
    """(village_id, taluk_id, district) for a point: from the file if given, else the nearest village."""
    a = areas.get()
    if taluk_id and a.taluk(taluk_id):
        v = a.nearest_village(lat, lon)
        return (v["village_id"] if v else None), taluk_id, a.taluk(taluk_id)["district"]
    v = a.nearest_village(lat, lon)
    return (v["village_id"], v["taluk_id"], v["district"]) if v else (None, None, None)


def _changed(c, key: str, digest: str) -> bool:
    r = c.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return not r or r["value"] != digest


def _remember(c, key: str, digest: str) -> None:
    c.execute("INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
              (key, digest))


def sync_from_csv(force: bool = False) -> dict:
    """Load changes from the two files. Returns counts of what's in the table afterwards."""
    with database.connect() as c:
        # Official list: replace details, drop centres removed from the file.
        digest = _file_hash(config.SHELTERS_CSV)
        if force or _changed(c, "shelters_csv", digest):
            rows = _read(config.SHELTERS_CSV)
            for r in rows:
                lat, lon = float(r["lat"]), float(r["lon"])
                village_id, taluk_id, district = _place(lat, lon, (r.get("taluk_id") or "").strip() or None)
                c.execute("""INSERT INTO shelters (shelter_id, village_id, name, name_kn, kind, lat, lon, capacity, phone,
                                                   source, designated, taluk_id, district)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'official', 1, ?, ?)
                             ON CONFLICT(shelter_id) DO UPDATE SET village_id = excluded.village_id, name = excluded.name,
                               name_kn = excluded.name_kn, kind = excluded.kind, lat = excluded.lat, lon = excluded.lon,
                               capacity = excluded.capacity, phone = excluded.phone, source = 'official', designated = 1,
                               taluk_id = excluded.taluk_id, district = excluded.district""",
                          (r["shelter_id"].strip(), village_id, r["name"].strip(), (r.get("name_kn") or "").strip() or None,
                           (r.get("kind") or "").strip() or None, lat, lon, int(r.get("capacity") or 0),
                           (r.get("phone") or "").strip() or None, taluk_id, district))
            keep = {r["shelter_id"].strip() for r in rows}
            gone = [x["shelter_id"] for x in c.execute("SELECT shelter_id FROM shelters WHERE source = 'official'")
                    if x["shelter_id"] not in keep]
            c.executemany("DELETE FROM shelters WHERE shelter_id = ?", [(g,) for g in gone])
            _remember(c, "shelters_csv", digest)

        # OpenStreetMap candidates: add new ones, refresh names/positions, never touch what a GP decided.
        digest = _file_hash(config.SHELTER_CANDIDATES_CSV)
        if force or _changed(c, "candidates_csv", digest):
            rows = _read(config.SHELTER_CANDIDATES_CSV)
            c.executemany("""INSERT INTO shelters (shelter_id, village_id, name, name_kn, kind, lat, lon, capacity, source,
                                                   designated, taluk_id, district)
                             VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'osm', 0, ?, ?)
                             ON CONFLICT(shelter_id) DO UPDATE SET name = excluded.name, name_kn = excluded.name_kn,
                               kind = excluded.kind, lat = excluded.lat, lon = excluded.lon""",
                          [(r["shelter_id"], r.get("village_id") or None, r["name"], r.get("name_kn") or None,
                            r.get("kind") or None, float(r["lat"]), float(r["lon"]), r.get("taluk_id") or None,
                            r.get("district") or None) for r in rows])
            ids = {r["shelter_id"] for r in rows}
            gone = [x["shelter_id"] for x in c.execute("SELECT shelter_id FROM shelters WHERE source = 'osm' AND designated = 0")
                    if x["shelter_id"] not in ids]
            c.executemany("DELETE FROM shelters WHERE shelter_id = ?", [(g,) for g in gone])
            _remember(c, "candidates_csv", digest)

        counts = {r["k"]: r["n"] for r in c.execute(
            "SELECT CASE WHEN designated = 1 THEN 'designated' ELSE 'candidates' END AS k, COUNT(*) AS n "
            "FROM shelters GROUP BY k")}
    return {"designated": counts.get("designated", 0), "candidates": counts.get("candidates", 0)}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance on the Earth's surface (haversine). Roads are longer, especially in the ghats."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _shape(r) -> dict:
    d = dict(r)
    for k in ("is_open", "sample", "designated"):
        d[k] = bool(d.get(k))
    d["spaces_left"] = max(0, d["capacity"] - d["occupancy"])
    d["status"] = ("candidate" if not d["designated"] else "closed" if not d["is_open"]
                   else "full" if d["occupancy"] >= d["capacity"] else "open")
    return d


def get(shelter_id: str) -> dict | None:
    with database.connect() as c:
        r = c.execute("SELECT * FROM shelters WHERE shelter_id = ?", (shelter_id,)).fetchone()
        return _shape(r) if r else None


def in_taluks(taluk_ids: set[str] | None, designated: bool = True, q: str = "", limit: int = 5000) -> list[dict]:
    """Designated centres (or candidates) in these taluks (None = all of Karnataka)."""
    sql, args = "SELECT * FROM shelters WHERE designated = ?", [int(designated)]
    if taluk_ids is not None:
        if not taluk_ids:
            return []
        sql += f" AND taluk_id IN ({', '.join('?' * len(taluk_ids))})"
        args += sorted(taluk_ids)
    if q.strip():
        sql += " AND (name LIKE ? OR name_kn LIKE ?)"
        args += [f"%{q.strip()}%"] * 2
    with database.connect() as c:
        return [_shape(r) for r in c.execute(sql + " ORDER BY taluk_id, name LIMIT ?", (*args, limit))]


def nearest(lat: float, lon: float, limit: int = 3) -> list[dict]:
    """Closest DESIGNATED centres. Open ones with space come first, but only within REACHABLE_KM:
    an open centre 45 km away over a ghat road is no use, so then the nearest ones are shown as they are."""
    box = 0.5     # degrees (~55 km): only look nearby
    with database.connect() as c:
        rows = c.execute("SELECT * FROM shelters WHERE designated = 1 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                         (lat - box, lat + box, lon - box, lon + box)).fetchall()
    out = []
    for r in rows:
        s = _shape(r)
        s["distance_km"] = round(distance_km(lat, lon, s["lat"], s["lon"]), 1)
        s["reachable"] = s["status"] == "open" and s["distance_km"] <= REACHABLE_KM
        out.append(s)
    out.sort(key=lambda s: (not s["reachable"], s["distance_km"]))
    return out[:limit]


def add(by: str, name: str, lat: float, lon: float, capacity: int, name_kn: str | None = None,
        phone: str | None = None, kind: str | None = None) -> dict:
    """A centre a Gram Panchayat official added on the map (designated straight away)."""
    village_id, taluk_id, district = _place(lat, lon)
    if not taluk_id:
        raise ValueError("That point is not near any Karnataka village.")
    sid = f"gp-{secrets.token_hex(4)}"
    with database.connect() as c:
        c.execute("""INSERT INTO shelters (shelter_id, village_id, name, name_kn, kind, lat, lon, capacity, phone, source,
                                           designated, taluk_id, district, added_by, updated_by, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'gp', 1, ?, ?, ?, ?, ?)""",
                  (sid, village_id, name.strip(), (name_kn or "").strip() or None, kind, lat, lon, capacity,
                   (phone or "").strip() or None, taluk_id, district, by, by, database.now()))
    return get(sid)


def update(shelter_id: str, by: str, is_open: bool | None = None, occupancy: int | None = None,
           designated: bool | None = None, capacity: int | None = None, phone: str | None = None) -> tuple[dict, dict]:
    """Change a centre. Returns (before, after). Rules:
      - only designated centres can be opened; designating needs a capacity
      - closing (or un-designating) a centre sets its head count to 0 (everyone has gone home)"""
    before = get(shelter_id)
    if before is None:
        raise KeyError(shelter_id)
    new = {"designated": before["designated"] if designated is None else designated,
           "capacity": before["capacity"] if capacity is None else capacity,
           "is_open": before["is_open"] if is_open is None else is_open,
           "occupancy": before["occupancy"] if occupancy is None else occupancy,
           "phone": before["phone"] if phone is None else (phone.strip() or None)}
    if new["designated"] and new["capacity"] < 1:
        raise ValueError("Give the number of people this centre can hold.")
    if is_open and not new["designated"]:
        raise ValueError("Mark it as a relief centre first.")
    if designated is False and before["designated"] and before["source"] != "osm":
        raise ValueError("Only possible centres from the map data can be un-marked; remove official ones from shelters.csv.")
    if not new["designated"]:
        new["is_open"] = False                  # un-marking a centre also closes it
    if occupancy and not new["is_open"]:
        raise ValueError("Open the centre before recording people inside.")
    if not new["is_open"]:
        new["occupancy"] = 0
    with database.connect() as c:
        c.execute("""UPDATE shelters SET designated = ?, capacity = ?, is_open = ?, occupancy = ?, phone = ?,
                     updated_by = ?, updated_at = ? WHERE shelter_id = ?""",
                  (int(new["designated"]), new["capacity"], int(new["is_open"]), new["occupancy"], new["phone"],
                   by, database.now(), shelter_id))
    return before, get(shelter_id)
