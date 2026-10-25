"""
Karnataka's districts, taluks and villages (about 28,000), loaded once from
ml/data/karnataka_villages.csv and ml/data/karnataka_areas.json (see ml/scripts/build_villages.py).

  village   one row per inhabited census village: name, district, taluk, position, rain-grid square
  taluk     id like "dakshina-kannada:belthangady"; Gram Panchayat officials are assigned one
  cell      IMD 0.25 degree rain-grid square ("12.75_75.25"); a village takes its square's risk

Search tolerates spelling differences between how people write a name and the census spelling
("Ujire" finds census "Ujre", "Belthangady" finds "Beltangadi"), and accepts Kannada script: "ಉಜಿರೆ" matches
the stored Kannada name, or, for villages without one yet, the census spelling it sounds like.

Kannada names come from ml/data/village_names_kn.csv and taluk_names_kn.csv (ml/scripts/fetch_kannada_names.py:
OpenStreetMap where mappers wrote them, AI-spelled otherwise) with hand corrections from name_kn_fixes.csv on top.
Each village and taluk says where its Kannada name came from (`name_kn_source`).
"""
import csv
import json
import math
import re
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache

from . import config, kannada

GRID_STEP = 0.25


def _skeleton(text: str) -> str:
    """Spelling-tolerant key: lower case, letters only, vowels after the first letter dropped,
    'h' dropped, doubled letters collapsed. 'Ujire' and 'Ujre' both become 'ujr'."""
    s = re.sub(r"[^a-z]", "", text.lower())
    for a, b in (("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("ph", "p"), ("sh", "s"),
                 ("ee", "i"), ("oo", "u"), ("w", "v"), ("y", "i"), ("z", "j"), ("x", "ks")):
        s = s.replace(a, b)
    if not s:
        return ""
    s = s[0] + re.sub(r"[aeiouh]", "", s[1:])         # h too: Subrahmanya = Subramanya
    return re.sub(r"(.)\1+", r"\1", s)


def _read_names(path, key: str) -> dict[str, tuple[str, str]]:
    """{id: (Kannada name, source)} from a names CSV; a missing file is simply no names."""
    out = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                kn = kannada.clean(r.get("name_kn"))
                if r.get(key) and kannada.has_kannada(kn):
                    out[r[key].strip()] = (kn, (r.get("source") or "").strip() or "file")
    except FileNotFoundError:
        pass
    return out


def _kn_key(text: str) -> str:
    """Kannada text for matching: tidied, no spaces."""
    return kannada.clean(text).replace(" ", "")


class Areas:
    def __init__(self, villages_csv, areas_json, village_names=None, taluk_names=None, fixes=None):
        self.villages: dict[str, dict] = {}
        self.by_taluk: dict[str, list[dict]] = defaultdict(list)
        self.by_cell: dict[str, list[dict]] = defaultdict(list)
        names = _read_names(village_names, "village_id") if village_names else {}
        tnames = _read_names(taluk_names, "taluk_id") if taluk_names else {}
        if fixes:                                   # one file for both: the id says which it is
            for k, (kn, _) in _read_names(fixes, "id").items():
                (tnames if ":" in k else names)[k] = (kn, "fix")
        with open(villages_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                kn, src = names.get(r["village_id"]) or ((kannada.clean(r["name_kn"]), "census file")
                                                        if kannada.has_kannada(r.get("name_kn")) else (None, None))
                v = {"village_id": r["village_id"], "name": r["name"], "district": r["district"],
                     "taluk": r["taluk"], "taluk_id": r["taluk_id"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                     "population": int(r["population"] or 0), "cell_id": r["cell_id"],
                     "name_kn": kn, "name_kn_source": src,
                     "_key": r["name"].lower(), "_skel": _skeleton(r["name"]), "_kn": _kn_key(kn) if kn else ""}
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
                kn, src = tnames.get(t["taluk_id"]) or ((t["name_kn"], "areas file") if t.get("name_kn") else (None, None))
                t = {**t, "name_kn": kn, "name_kn_source": src, "district": d["name"], "district_kn": d.get("name_kn")}
                self.taluks[t["taluk_id"]] = t
                ts.append({k: t[k] for k in ("taluk_id", "name", "name_kn", "villages")})
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
        """Villages by name: exact start of name first, then contains, then same sound, then sound prefix.
        Bigger villages first within each group."""
        pool = self.by_taluk.get(taluk_id, []) if taluk_id else (
            [v for v in self.villages.values() if v["district"].lower() == district.lower()] if district
            else self.villages.values())
        q = (q or "").strip().lower()
        if not q:
            return sorted(pool, key=lambda v: v["name"])[:limit]
        kq = _kn_key(q) if kannada.has_kannada(q) else ""
        latin = re.sub(r"[^a-z]", "", kannada.romanize(q) if kq else q)
        skel = _skeleton(latin)                               # Kannada typed: compare by sound with census names
        ranked = []
        for v in pool:
            if kq and v["_kn"].startswith(kq):
                rank = 0
            elif kq and kq in v["_kn"]:
                rank = 1
            elif not kq and v["_key"].startswith(q):
                rank = 0
            elif not kq and q in v["_key"]:
                rank = 1
            elif skel and v["_skel"] == skel:
                rank = 2                                      # sounds the same: Ujire / Ujre, ಕೊಕ್ಕಡ / Kokkada
            elif skel and v["_skel"].startswith(skel):
                rank = 3
            else:
                continue
            # among sound matches, closer spellings first ("ಕೊಕ್ಕಡ": Kokkada before Kod), then bigger villages
            close = 0.0 if rank < 2 else round(1 - SequenceMatcher(None, latin, re.sub(r"[^a-z]", "", v["_key"])).ratio(), 1)
            ranked.append((rank, close, -v["population"], v["name"], v))
        ranked.sort(key=lambda x: x[:4])
        return [x[4] for x in ranked[:limit]]

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
    return {k: v[k] for k in ("village_id", "name", "name_kn", "name_kn_source", "district", "taluk", "taluk_id",
                              "lat", "lon", "population", "cell_id")}


def _stamp(path) -> float:
    try:
        return path.stat().st_mtime
    except (FileNotFoundError, AttributeError):
        return 0.0


@lru_cache(maxsize=4)
def _load(villages_csv: str, areas_json: str, names: tuple, _stamps: tuple) -> Areas:
    return Areas(villages_csv, areas_json, *names)


def get() -> Areas:
    """The loaded areas. Re-read automatically when a Kannada names file changes (no server restart needed)."""
    names = (config.VILLAGE_NAMES_KN_CSV, config.TALUK_NAMES_KN_CSV, config.NAME_KN_FIXES_CSV)
    return _load(str(config.VILLAGES_CSV), str(config.AREAS_JSON), tuple(str(p) for p in names),
                 tuple(_stamp(p) for p in names))
