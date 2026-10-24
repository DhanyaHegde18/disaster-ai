"""
State-wide village list for Karnataka, from Census village boundaries.

Source : DataMeet "Indian Village Boundaries", Karnataka file (ODbL licence)
         https://github.com/datameet/indian_village_boundaries  ->  ka/ka.geojson  (~87 MB)
         Census 2011 villages on 2001 district/taluk boundaries.
What it does:
  - one row per village (duplicate pieces of the same village merged), uninhabited villages dropped
  - position = centre of the village boundary
  - district renamed to today's 31 districts (Ramanagara, Chikkaballapura, Yadgir and Vijayanagara
    were carved out later) and today's spellings (Belagavi, Kalaburagi, Mysuru ...)
  - taluk spellings modernised where the change is well known; the census spelling is kept for search
  - each village is linked to the IMD 0.25 degree rain grid square it falls in (cell_id)
Output : ml/data/karnataka_villages.csv   village_id, name, district, taluk, taluk_id, lat, lon, population, cell_id
         ml/data/karnataka_areas.json      districts (with Kannada names) and their taluks
Limits : new taluks created after 2011 (e.g. Kadaba, Moodbidri) still show under their old taluk;
         Kannada village names aren't in this source (English only for now).

Run from the project root (only needed if you want to rebuild; the CSV is already in the project):
    curl -L -o ml/data/raw/ka.geojson https://raw.githubusercontent.com/datameet/indian_village_boundaries/master/ka/ka.geojson
    python ml/scripts/build_villages.py --geojson ml/data/raw/ka.geojson
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_CSV = ROOT / "ml" / "data" / "karnataka_villages.csv"
OUT_AREAS = ROOT / "ml" / "data" / "karnataka_areas.json"

GRID_STEP, GRID_LAT0, GRID_LON0 = 0.25, 6.5, 66.5     # IMD 0.25 degree grid (cell centres)

# Census (2001) district name -> today's district
DISTRICT = {
    "Bagalkot": "Bagalkote", "Bangalore": "Bengaluru Urban", "Bangalore Rural": "Bengaluru Rural",
    "Belgaum": "Belagavi", "Bellary": "Ballari", "Bidar": "Bidar", "Bijapur": "Vijayapura",
    "Chamarajnagar": "Chamarajanagar", "Chikmagalur": "Chikkamagaluru", "Chitradurga": "Chitradurga",
    "Dakshina Kannada": "Dakshina Kannada", "Davangere": "Davanagere", "Dharwad": "Dharwad", "Gadag": "Gadag",
    "Gulbarga": "Kalaburagi", "Hassan": "Hassan", "Haveri": "Haveri", "Kodagu": "Kodagu", "Kolar": "Kolar",
    "Koppal": "Koppal", "Mandya": "Mandya", "Mysore": "Mysuru", "Raichur": "Raichur", "Shimoga": "Shivamogga",
    "Tumkur": "Tumakuru", "Udupi": "Udupi", "Uttar Kannad": "Uttara Kannada",
}
# Taluks that moved to districts created after 2001 (census spelling)
NEW_DISTRICT = {
    "Ramanagaram": "Ramanagara", "Channapatna": "Ramanagara", "Kankapura": "Ramanagara", "Magadi": "Ramanagara",
    "Chikballapur": "Chikkaballapura", "Bagepalli": "Chikkaballapura", "Chintamani": "Chikkaballapura",
    "Gauribidanur": "Chikkaballapura", "Gudibanda": "Chikkaballapura", "Sidlaghatta": "Chikkaballapura",
    "Yadgir": "Yadgir", "Shahpur": "Yadgir", "Shorapur": "Yadgir",
    "Hospet": "Vijayanagara", "Hagaribommanahalli": "Vijayanagara", "Hadagalli": "Vijayanagara",
    "Kudligi": "Vijayanagara", "Harpanahalli": "Vijayanagara",
}
DISTRICT_KN = {
    "Bagalkote": "ಬಾಗಲಕೋಟೆ", "Ballari": "ಬಳ್ಳಾರಿ", "Belagavi": "ಬೆಳಗಾವಿ", "Bengaluru Rural": "ಬೆಂಗಳೂರು ಗ್ರಾಮಾಂತರ",
    "Bengaluru Urban": "ಬೆಂಗಳೂರು ನಗರ", "Bidar": "ಬೀದರ್", "Chamarajanagar": "ಚಾಮರಾಜನಗರ",
    "Chikkaballapura": "ಚಿಕ್ಕಬಳ್ಳಾಪುರ", "Chikkamagaluru": "ಚಿಕ್ಕಮಗಳೂರು", "Chitradurga": "ಚಿತ್ರದುರ್ಗ",
    "Dakshina Kannada": "ದಕ್ಷಿಣ ಕನ್ನಡ", "Davanagere": "ದಾವಣಗೆರೆ", "Dharwad": "ಧಾರವಾಡ", "Gadag": "ಗದಗ",
    "Hassan": "ಹಾಸನ", "Haveri": "ಹಾವೇರಿ", "Kalaburagi": "ಕಲಬುರಗಿ", "Kodagu": "ಕೊಡಗು", "Kolar": "ಕೋಲಾರ",
    "Koppal": "ಕೊಪ್ಪಳ", "Mandya": "ಮಂಡ್ಯ", "Mysuru": "ಮೈಸೂರು", "Raichur": "ರಾಯಚೂರು", "Ramanagara": "ರಾಮನಗರ",
    "Shivamogga": "ಶಿವಮೊಗ್ಗ", "Tumakuru": "ತುಮಕೂರು", "Udupi": "ಉಡುಪಿ", "Uttara Kannada": "ಉತ್ತರ ಕನ್ನಡ",
    "Vijayanagara": "ವಿಜಯನಗರ", "Vijayapura": "ವಿಜಯಪುರ", "Yadgir": "ಯಾದಗಿರಿ",
}
# Census taluk spelling -> today's common spelling (only well-known changes)
TALUK = {
    "Afsalpur": "Afzalpur", "Athni": "Athani", "Bangalore North": "Bengaluru North", "Bangalore South": "Bengaluru South",
    "Bantval": "Bantwal", "Belgaum": "Belagavi", "Bellary": "Ballari", "Beltangadi": "Belthangady", "Bijapur": "Vijayapura",
    "Bydagi": "Byadgi", "Chamarajnagar": "Chamarajanagar", "Chikballapur": "Chikkaballapura", "Chikmagalur": "Chikkamagaluru",
    "Chiknayakanhalli": "Chikkanayakanahalli", "Coondapur": "Kundapura", "Davangere": "Davanagere",
    "Devanhalli": "Devanahalli", "Dod Ballapur": "Doddaballapura", "Gangawati": "Gangavathi", "Gulbarga": "Kalaburagi",
    "Hadagalli": "Huvina Hadagalli", "Harpanahalli": "Harapanahalli", "Heggadadevankote": "H.D. Kote",
    "Hole Narsipur": "Holenarasipura", "Hospet": "Hosapete", "Kalghatgi": "Kalaghatagi", "Kankapura": "Kanakapura",
    "Karkal": "Karkala", "Kollegal": "Kollegala", "Korategere": "Koratagere", "Krishnarajanagara": "K.R. Nagar",
    "Krishnarajpet": "Krishnarajapete", "Malvalli": "Malavalli", "Mangalore": "Mangaluru", "Mysore": "Mysuru",
    "Nelamagala": "Nelamangala", "Piriyapatana": "Periyapatna", "Ramanagaram": "Ramanagara", "Ranibenur": "Ranebennur",
    "Raybag": "Raibag", "Shimoga": "Shivamogga", "Shrirangapattana": "Srirangapatna", "Sindhnur": "Sindhanur",
    "Somvarpet": "Somwarpet", "Sorab": "Soraba", "Sulya": "Sullia", "Supa": "Joida",
    "Tirumakudal Narsipur": "T. Narasipura", "Tumkur": "Tumakuru", "Yelbarga": "Yelburga",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def ring_centroid(ring: list) -> tuple[float, float, float]:
    """(area, lon, lat) of one polygon ring by the shoelace formula (fine at village scale)."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-15:                                    # degenerate: plain average
        xs, ys = zip(*ring)
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def centroid(geom: dict) -> tuple[float, float, float]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    parts = [ring_centroid([tuple(p[:2]) for p in poly[0]]) for poly in polys if poly and poly[0]]
    total = sum(a for a, _, _ in parts)
    if total == 0:
        return 0.0, parts[0][1], parts[0][2]
    return (total, sum(a * x for a, x, _ in parts) / total, sum(a * y for a, _, y in parts) / total)


def cell_of(lat: float, lon: float) -> str:
    clat = GRID_LAT0 + round((lat - GRID_LAT0) / GRID_STEP) * GRID_STEP
    clon = GRID_LON0 + round((lon - GRID_LON0) / GRID_STEP) * GRID_STEP
    return f"{clat:.2f}_{clon:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geojson", required=True, type=Path)
    args = ap.parse_args()

    features = json.loads(args.geojson.read_text(encoding="utf-8"))["features"]
    best = {}                                             # LOC_CODE -> (area, row): keep the biggest piece
    for f in features:
        p, g = f["properties"], f.get("geometry")
        if not g:
            continue
        population = int(p.get("T_P") or 0) or int(p.get("T_POPLN") or 0)
        if population <= 0:
            continue                                      # uninhabited village
        area, lon, lat = centroid(g)
        census_taluk = p["TALUK"].strip()
        district = NEW_DISTRICT.get(census_taluk) or DISTRICT[p["DISTRICT"].strip()]
        taluk = TALUK.get(census_taluk, census_taluk)
        row = {"village_id": p["LOC_CODE"], "name": p["NAME"].strip().title(), "district": district,
               "taluk": taluk, "taluk_id": f"{slug(district)}:{slug(taluk)}", "census_taluk": census_taluk,
               "lat": round(lat, 5), "lon": round(lon, 5), "population": population, "cell_id": cell_of(lat, lon)}
        if row["village_id"] not in best or area > best[row["village_id"]][0]:
            best[row["village_id"]] = (area, row)

    rows = sorted((r for _, r in best.values()), key=lambda r: (r["district"], r["taluk"], r["name"]))
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    taluks = defaultdict(dict)
    for r in rows:
        t = taluks[r["district"]].setdefault(r["taluk_id"], {"taluk_id": r["taluk_id"], "name": r["taluk"],
                                                            "census_name": r["census_taluk"], "villages": 0,
                                                            "cells": set()})
        t["villages"] += 1
        t["cells"].add(r["cell_id"])
    areas = {"source": "DataMeet Indian Village Boundaries (Census 2011), ODbL",
             "districts": [{"name": d, "name_kn": DISTRICT_KN[d],
                            "taluks": sorted(({**t, "cells": sorted(t["cells"])} for t in ts.values()),
                                             key=lambda t: t["name"])}
                           for d, ts in sorted(taluks.items())]}
    OUT_AREAS.write_text(json.dumps(areas, ensure_ascii=False, indent=1), encoding="utf-8")

    cells = {r["cell_id"] for r in rows}
    print(f"{len(rows)} villages, {len(areas['districts'])} districts, "
          f"{sum(len(d['taluks']) for d in areas['districts'])} taluks, {len(cells)} rain-grid squares")
    print(f"saved {OUT_CSV} and {OUT_AREAS}")


if __name__ == "__main__":
    main()
