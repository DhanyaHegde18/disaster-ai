"""
Past landslides in Karnataka, the "answers" the landslide model learns from.

Source : NASA Global Landslide Catalog + Landslide Reporter (COOLR), free.
         Download once by hand (no direct link is published):
           1. open https://maps.nccs.nasa.gov/arcgis/apps/MapAndAppGallery/index.html?appid=574f26408683485799d02e857e5d9521
           2. click "Download Landslide Catalog", choose CSV
           3. save the file (any name ending .csv) in  ml/data/raw/landslides/
         Cite: Kirschbaum et al. 2010 (Natural Hazards) and 2015 (Geomorphology); for Landslide Reporter
         entries Juang, Stanley & Kirschbaum 2019 (PLOS ONE).
         Also added: the landslides in ml/data/events.csv that you researched yourself.

What is kept
  - inside Karnataka (within 15 km of a census village)
  - location known to 25 km or better (the catalog says how accurate each point is)
  - triggered by rain (downpour, monsoon, continuous rain, cyclone, flooding) or trigger unknown
  - one row per rain-grid square per day (several reports of the same slide are merged)
Output : ml/data/landslides_karnataka.csv   date, lat, lon, cell_id, taluk_id, accuracy, trigger, source, title

Run from the project root:
    python ml/scripts/fetch_landslides.py --auto     # download from NASA's map server automatically
    python ml/scripts/fetch_landslides.py            # use CSVs you saved in ml/data/raw/landslides/
"""
import argparse
import csv
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import areas  # noqa: E402

IN_DIR = ROOT / "ml" / "data" / "raw" / "landslides"
OUT = ROOT / "ml" / "data" / "landslides_karnataka.csv"
MAX_KM_FROM_VILLAGE = 15
GOOD_ACCURACY = {"exact", "1km", "5km", "10km", "25km"}
RAIN_TRIGGERS = ("rain", "downpour", "monsoon", "cyclone", "flood", "storm", "unknown")

# The catalog has been exported with slightly different column names over the years.
COLUMNS = {
    "date": ["event_date", "date", "ev_date", "eventdate"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "lon", "long", "lng", "x"],
    "accuracy": ["location_accuracy", "loc_acc", "accuracy"],
    "trigger": ["landslide_trigger", "trigger", "event_trigger"],
    "category": ["landslide_category", "category", "ls_cat", "ls_type"],
    "title": ["event_title", "title", "event_description", "location_description"],
    "country": ["country_name", "country", "countryname"],
}


def pick(row: dict, key: str) -> str:
    low = {k.lower().strip(): v for k, v in row.items() if k}
    for name in COLUMNS[key]:
        if name in low and low[name] not in (None, ""):
            return str(low[name]).strip()
    return ""


def parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 12:                       # ArcGIS exports: milliseconds since 1970
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).date()
    formats = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
               "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d-%m-%Y")
    for candidate in (text, text[:22], text[:19], text[:10]):
        for fmt in formats:
            try:
                return datetime.strptime(candidate.strip(), fmt).date()
            except ValueError:
                continue
    return None


def date_in_title(title: str) -> date | None:
    """COOLR event inventories put the event date in the title, e.g. 'Manual, Kodagu, 2018-08-16'."""
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2})", title or "")
    return parse_date(m.group(1)) if m else None


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def read_catalog(a) -> tuple[list[dict], dict]:
    files = sorted(IN_DIR.glob("*.csv"))
    skipped = {"outside Karnataka": 0, "location too vague": 0, "not rain": 0, "no date": 0, "not a landslide": 0}
    rows = []
    for f in files:
        with open(f, newline="", encoding="utf-8-sig", errors="replace") as fh:
            for r in csv.DictReader(fh):
                try:
                    lat, lon = float(pick(r, "lat")), float(pick(r, "lon"))
                except ValueError:
                    continue
                if not (11.0 < lat < 19.0 and 73.5 < lon < 79.0):
                    continue                                   # quick box test before the village lookup
                v = a.nearest_village(lat, lon)
                if not v or km(lat, lon, v["lat"], v["lon"]) > MAX_KM_FROM_VILLAGE:
                    skipped["outside Karnataka"] += 1
                    continue
                acc = pick(r, "accuracy").lower().replace(" ", "")
                if acc and acc not in GOOD_ACCURACY:
                    skipped["location too vague"] += 1
                    continue
                trig = pick(r, "trigger").lower()
                if trig and not any(t in trig for t in RAIN_TRIGGERS):      # empty trigger = unknown: kept
                    skipped["not rain"] += 1
                    continue
                cat = pick(r, "category").lower()
                if any(w in cat for w in ("snow", "avalanche", "lahar")):
                    skipped["not a landslide"] += 1
                    continue
                d = parse_date(pick(r, "date")) or date_in_title(pick(r, "title"))
                if not d:
                    skipped["no date"] += 1
                    continue
                rows.append({"date": d.isoformat(), "lat": round(lat, 5), "lon": round(lon, 5), "cell_id": v["cell_id"],
                             "taluk_id": v["taluk_id"], "accuracy": acc or "unknown", "trigger": trig or "unknown",
                             "source": f"NASA catalog ({f.name})", "title": pick(r, "title")[:120]})
    return rows, skipped


def own_events(a) -> list[dict]:
    """The landslides you collected earlier in ml/data/events.csv (places in ml/data/villages.csv)."""
    ev, vs = ROOT / "ml" / "data" / "events.csv", ROOT / "ml" / "data" / "villages.csv"
    if not (ev.exists() and vs.exists()):
        return []
    places = {r["village_id"]: r for r in csv.DictReader(open(vs, encoding="utf-8"))}
    out = []
    for r in csv.DictReader(open(ev, encoding="utf-8")):
        if r.get("event_type", "").strip() != "landslide" or r["village_id"] not in places:
            continue
        p = places[r["village_id"]]
        v = a.nearest_village(float(p["lat"]), float(p["lon"]))
        if v:
            out.append({"date": r["date"], "lat": float(p["lat"]), "lon": float(p["lon"]), "cell_id": v["cell_id"],
                        "taluk_id": v["taluk_id"], "accuracy": "5km", "trigger": "rain", "source": "events.csv",
                        "title": f"{p['name']} landslide"})
    return out


# ---------- automatic download from NASA's public ArcGIS map server ----------
SERVERS = ["https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides",
           "https://maps.nccs.nasa.gov/mapping/rest/services/COOLR"]
# Layers known to exist (folder listings are sometimes switched off). Reports = news + citizen reports (GLC, LRC);
# Events = landslides mapped from satellite images. Names that don't exist are simply skipped.
KNOWN_LAYERS = [f"{base}/{svc}/{kind}/0"
                for base, svcs in (("https://gis.earthdata.nasa.gov/gis05/rest/services/Landslides",
                                    ("COOLR_Reports_Points", "COOLR_Events_Points", "COOLR_Events_Polygons")),
                                   ("https://maps.nccs.nasa.gov/mapping/rest/services/COOLR",
                                    ("COOLR_Reports_Point", "COOLR_Events_Point", "COOLR_Events_Polygon")))
                for svc in svcs for kind in ("FeatureServer", "MapServer")]
KA_BOX = (73.5, 11.0, 79.0, 19.0)                     # lon min, lat min, lon max, lat max


def _get_json(session, url: str, **params) -> dict:
    r = session.get(url, params={"f": "json", **params}, timeout=120)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(str(data["error"])[:200])
    return data


def point_layers(session, folder: str) -> list[tuple[str, str]]:
    """(layer URL, name) for every point layer in a folder of map services."""
    out = []
    for svc in _get_json(session, folder).get("services", []):
        if svc.get("type") not in ("MapServer", "FeatureServer"):
            continue
        base = folder.rsplit("/", 1)[0] + "/" + svc["name"] + "/" + svc["type"]
        try:
            layers = _get_json(session, base).get("layers", [])
        except Exception as err:
            print(f"  skip {svc['name']}: {err}")
            continue
        for lyr in layers:
            if lyr.get("geometryType", "esriGeometryPoint") == "esriGeometryPoint" and not lyr.get("subLayerIds"):
                out.append((f"{base}/{lyr['id']}", f"{svc['name']}/{lyr.get('name', lyr['id'])}"))
    return out


def download_layer(session, layer_url: str) -> list[dict]:
    """Every feature of a layer inside Karnataka's box, as flat rows with latitude/longitude."""
    rows, offset = [], 0
    while True:
        data = _get_json(session, f"{layer_url}/query", where="1=1", outFields="*", returnGeometry="true",
                         geometry=",".join(map(str, KA_BOX)), geometryType="esriGeometryEnvelope", inSR=4326,
                         spatialRel="esriSpatialRelIntersects", outSR=4326, resultOffset=offset, resultRecordCount=1000)
        feats = data.get("features", [])
        for f in feats:
            g = f.get("geometry") or {}
            if "x" in g and "y" in g:
                x, y = g["x"], g["y"]
            elif g.get("rings") and g["rings"][0]:              # outline of a mapped landslide: use its centre
                ring = g["rings"][0]
                x, y = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            else:
                continue
            rows.append({**{k: ("" if v is None else v) for k, v in f.get("attributes", {}).items()},
                         "longitude": x, "latitude": y})
        if not feats or not data.get("exceededTransferLimit"):
            return rows
        offset += len(feats)


def auto_download() -> int:
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "disaster-ai student project (Karnataka landslide model)"
    IN_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    layers, seen = [], set()
    for folder in SERVERS:
        try:
            layers += point_layers(session, folder)
        except Exception as err:
            print(f"could not list {folder} ({type(err).__name__}); trying its known layers directly")
    for url in KNOWN_LAYERS:
        layers.append((url, url.split("/services/")[1].replace("/0", "")))
    for url, name in layers:
        key = name.split("/")[-2] if "/" in name else name             # the same service via Map- and FeatureServer
        if key in seen:
            continue
        try:
            rows = download_layer(session, url)
        except Exception as err:
            if "404" not in str(err) and "not found" not in str(err).lower():
                print(f"  {name}: failed ({str(err)[:100]})")
            continue
        seen.add(key)
        if not rows:
            print(f"  {name}: answered, but no landslides in the Karnataka area")
            continue
        out = IN_DIR / ("auto_" + "".join(ch if ch.isalnum() else "_" for ch in name) + ".csv")
        keys = sorted({k for r in rows for k in r})
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        total += len(rows)
        print(f"  {name}: {len(rows)} landslides in the Karnataka area -> {out.name}")
    if not total:
        print("Automatic download found nothing. Download the CSV by hand (see the top of this file).")
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="download from NASA's map server first")
    args = ap.parse_args()
    a = areas.get()
    IN_DIR.mkdir(parents=True, exist_ok=True)
    if args.auto:
        auto_download()
    rows, skipped = read_catalog(a)
    if not rows:
        print(f"No NASA catalog rows found in {IN_DIR}. Download the CSV first (see the top of this file).")
    mine = own_events(a)
    seen, merged = set(), []
    for r in sorted(rows + mine, key=lambda r: (r["date"], r["cell_id"])):
        key = (r["date"], r["cell_id"])
        if key in seen:
            continue                                           # same square, same day: one landslide day
        seen.add(key)
        merged.append(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "lat", "lon", "cell_id", "taluk_id", "accuracy", "trigger", "source", "title"])
        w.writeheader()
        w.writerows(merged)
    years = {}
    for r in merged:
        years[r["date"][:4]] = years.get(r["date"][:4], 0) + 1
    print(f"{len(rows)} catalog landslides kept + {len(mine)} from events.csv -> {len(merged)} landslide square-days")
    print("  skipped: " + ", ".join(f"{k} {n}" for k, n in skipped.items() if n))
    print("  by year: " + ", ".join(f"{y}: {n}" for y, n in sorted(years.items())))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
