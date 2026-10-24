"""
Possible relief centres for all of Karnataka from OpenStreetMap: schools, colleges, community halls
and Gram Panchayat / town halls, the buildings district administrations usually open as
ಕಾಳಜಿ ಕೇಂದ್ರ. They are NOT relief centres until a Gram Panchayat official designates one on the
dashboard (and gives its capacity); villagers never see undesignated ones.

Source : OpenStreetMap via the Overpass API (free, no key). Data (c) OpenStreetMap contributors, ODbL.
Output : ml/data/shelter_candidates.csv
         shelter_id, name, name_kn, kind, lat, lon, village_id, taluk_id, district
         (each building is linked to the taluk of its nearest village)
Only named buildings are kept: an official needs to recognise the place.

Run from the project root (takes a few minutes; Overpass can be busy, it retries other servers):
    python ml/scripts/fetch_osm_buildings.py
Then restart the server: new candidates load automatically, designated ones are kept.
"""
import csv
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import areas  # noqa: E402  (village lookup, to give each building its taluk)

OUT = ROOT / "ml" / "data" / "shelter_candidates.csv"
SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
KINDS = {"school": "school", "college": "college", "community_centre": "community hall",
         "townhall": "panchayat / town hall"}
QUERY = """
[out:json][timeout:600];
area["ISO3166-2"="IN-KA"]["admin_level"="4"]->.ka;
nwr["amenity"~"^(school|college|community_centre|townhall)$"]["name"](area.ka);
out center tags;
"""
KANNADA = re.compile(r"[ಀ-೿]")


def fetch() -> list[dict]:
    for url in SERVERS:
        for attempt in range(1, 3):
            try:
                print(f"asking {url} (attempt {attempt}) ... this can take a few minutes")
                r = requests.post(url, data={"data": QUERY}, timeout=900,
                                  headers={"User-Agent": "disaster-ai student project (relief centre candidates)"})
                if r.status_code in (429, 504):
                    print(f"  busy ({r.status_code}); waiting 60 s")
                    time.sleep(60)
                    continue
                r.raise_for_status()
                return r.json()["elements"]
            except (requests.RequestException, ValueError) as err:
                print(f"  failed: {type(err).__name__}: {str(err)[:120]}")
                time.sleep(10)
    raise SystemExit("All Overpass servers failed. Try again later (they are free and sometimes overloaded).")


def main() -> None:
    elements = fetch()
    print(f"{len(elements)} named buildings received; matching each to a taluk ...")
    a = areas.get()
    rows, outside = [], 0
    for e in elements:
        tags = e.get("tags", {})
        lat = e.get("lat", e.get("center", {}).get("lat"))
        lon = e.get("lon", e.get("center", {}).get("lon"))
        if lat is None or lon is None:
            continue
        v = a.nearest_village(lat, lon)
        if not v:
            outside += 1
            continue
        name = tags.get("name", "").strip()
        name_kn = tags.get("name:kn") or (name if KANNADA.search(name) else None)
        if KANNADA.search(name) and tags.get("name:en"):
            name = tags["name:en"].strip()           # English first on the dashboard, Kannada alongside
        rows.append({"shelter_id": f"osm-{e['type'][0]}{e['id']}", "name": name, "name_kn": name_kn or "",
                     "kind": KINDS.get(tags.get("amenity"), tags.get("amenity")),
                     "lat": round(lat, 6), "lon": round(lon, 6), "village_id": v["village_id"],
                     "taluk_id": v["taluk_id"], "district": v["district"]})
    rows.sort(key=lambda r: (r["taluk_id"], r["name"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["shelter_id"])
        w.writeheader()
        w.writerows(rows)
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    print(f"saved {len(rows)} possible centres to {OUT} ({outside} skipped: not near a village)")
    print("  " + ", ".join(f"{k}: {n}" for k, n in sorted(by_kind.items(), key=lambda x: -x[1])))
    print("Restart the server to load them.")


if __name__ == "__main__":
    main()
