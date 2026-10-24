"""
Karnataka's districts, taluks and villages (about 28,000), loaded once from
ml/data/karnataka_villages.csv and ml/data/karnataka_areas.json (see ml/scripts/build_villages.py).

  village   one row per inhabited census village: name, district, taluk, position, rain-grid square
  taluk     id like "dakshina-kannada:belthangady"; Gram Panchayat officials are assigned one
  cell      IMD 0.25 degree rain-grid square ("12.75_75.25"); a village takes its square's risk

Search tolerates spelling differences between how people write a name and the census spelling
("Ujire" finds census "Ujre", "Belthangady" finds "Beltangadi").
"""
import csv
import json
import math
import re
from collections import defaultdict
from functools import lru_cache

from . import config

GRID_STEP = 0.25


def _skeleton(text: str) -> str:
    """Spelling-tolerant key: lower case, letters only, vowels after the first letter dropped,
    'h' dropped, doubled letters collapsed. 'Ujire' and 'Ujre' both become 'ujr'."""
    s = re.sub(r"[^a-z]", "", text.lower())
    for a, b in (("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("ph", "p"), ("sh", "s"),
                 ("ee", "i"), ("oo", "u"), ("w", "v"), ("y", "i"), ("z", "j")):
        s = s.replace(a, b)
    if not s:
        return ""
    s = s[0] + re.sub(r"[aeiouh]", "", s[1:])         # h too: Subrahmanya = Subramanya
    return re.sub(r"(.)\1+", r"\1", s)


class Areas:
    def __init__(self, villages_csv, areas_json):
        self.villages: dict[str, dict] = {}
        self.by_taluk: dict[str, list[dict]] = defaultdict(list)
        self.by_cell: dict[str, list[dict]] = defaultdict(list)
        with open(villages_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                v = {"village_id": r["village_id"], "name": r["name"], "district": r["district"],
                     "taluk": r["taluk"], "taluk_id": r["taluk_id"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                     "population": int(r["population"] or 0), "cell_id": r["cell_id"],
                     "name_kn": r.get("name_kn") or None,
                     "_key": r["name"].lower(), "_skel": _skeleton(r["name"])}
                self.villages[v["village_id"]] = v
                self.by_taluk[v["taluk_id"]].append(v)
                self.by_cell[v["cell_id"]].append(v)
        data = json.loads(open(areas_json, encoding="utf-8").read())
        self.districts = []
        self.taluks: dict[str, dict] = {}
        self.district_kn = {}
        for d in data["districts"]:
            self.district_kn[d["name"]] = d.get("name_kn")
            ts = []
            for t in d["taluks"]:
                t = {**t, "district": d["name"], "district_kn": d.get("name_kn")}
                self.taluks[t["taluk_id"]] = t
                ts.append({k: t[k] for k in ("taluk_id", "name", "villages")})
            self.districts.append({"name": d["name"], "name_kn": d.get("name_kn"), "taluks": ts})
        # cells per taluk/district for scoping the risk view
        self.cells_by_taluk = {tid: set(t["cells"]) for tid, t in self.taluks.items()}

    # ----- lookups -----
    def village(self, village_id: str) -> dict | None:
        return self.villages.get(village_id)

    def taluk(self, taluk_id: str) -> dict | None:
        return self.taluks.get(taluk_id)

    def taluks_in_district(self, district: str) -> list[str]:
        return [tid for tid, t in self.taluks.items() if t["district"].lower() == (district or "").lower()]

    def find_taluk(self, name: str, district: str | None = None) -> list[dict]:
        """Taluks matching a typed name (census or modern spelling), optionally within a district."""
        key = _skeleton(name)
        out = [t for t in self.taluks.values()
               if (not district or t["district"].lower() == district.lower())
               and key in (_skeleton(t["name"]), _skeleton(t.get("census_name", "")))]
        return out

    def find_district(self, name: str) -> str | None:
        key = _skeleton(name)
        for d in self.districts:
            if _skeleton(d["name"]) == key:
                return d["name"]
        return None

    def search(self, q: str, taluk_id: str | None = None, district: str | None = None, limit: int = 30) -> list[dict]:
        """Villages by name: exact start of name first, then contains, then spelling-tolerant match.
        Bigger villages first within each group."""
        pool = self.by_taluk.get(taluk_id, []) if taluk_id else (
            [v for v in self.villages.values() if v["district"].lower() == district.lower()] if district
            else self.villages.values())
        q = (q or "").strip().lower()
        if not q:
            return sorted(pool, key=lambda v: v["name"])[:limit]
        skel = _skeleton(q)
        ranked = []
        for v in pool:
            if v["_key"].startswith(q):
                rank = 0
            elif q in v["_key"]:
                rank = 1
            elif skel and v["_skel"].startswith(skel):
                rank = 2
            else:
                continue
            ranked.append((rank, -v["population"], v["name"], v))
        ranked.sort(key=lambda x: x[:3])
        return [x[3] for x in ranked[:limit]]

    def nearest_village(self, lat: float, lon: float) -> dict | None:
        """Closest village centre, searching this rain-grid square and its neighbours."""
        best, best_d = None, float("inf")
        clat = round((lat - 6.5) / GRID_STEP) * GRID_STEP + 6.5
        clon = round((lon - 66.5) / GRID_STEP) * GRID_STEP + 66.5
        for dlat in (-GRID_STEP, 0, GRID_STEP):
            for dlon in (-GRID_STEP, 0, GRID_STEP):
                for v in self.by_cell.get(f"{clat + dlat:.2f}_{clon + dlon:.2f}", []):
                    d = (v["lat"] - lat) ** 2 + ((v["lon"] - lon) * math.cos(math.radians(lat))) ** 2
                    if d < best_d:
                        best, best_d = v, d
        return best


def public(v: dict) -> dict:
    """A village as the API shows it (no internal search keys)."""
    return {k: v[k] for k in ("village_id", "name", "name_kn", "district", "taluk", "taluk_id",
                              "lat", "lon", "population", "cell_id")}


@lru_cache
def _load(villages_csv: str, areas_json: str) -> Areas:
    return Areas(villages_csv, areas_json)


def get() -> Areas:
    return _load(str(config.VILLAGES_CSV), str(config.AREAS_JSON))
