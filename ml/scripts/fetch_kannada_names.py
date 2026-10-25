"""
Kannada names for every village and taluk, so villagers can read and type their village in Kannada.

The government's Local Government Directory has a "local name" column, but for Karnataka it is empty for
almost every village (64 of 30,775 in October 2026), so names are collected in two steps instead:

  1. OpenStreetMap: villages that mappers named in Kannada (place nodes with name:kn, or a Kannada name).
     Each of our census villages takes the closest such place within 3 km whose Kannada name SOUNDS LIKE
     the census spelling (backend/app/kannada.py romanizes it and compares on the spelling-tolerant
     skeleton), so a neighbouring village's name is never borrowed.
  2. Gemini, for the rest: batches of villages with their taluk and district, asked for the spelling used
     on Karnataka government records. Every answer is checked: Kannada script only, and it must sound
     like the census spelling, otherwise it is dropped. Biggest villages go first, so if the free daily
     quota runs out the villages most people live in already have names. Re-running continues where
     it stopped.

Hand corrections go in ml/data/name_kn_fixes.csv (id,name_kn - a village id like 617935 or a taluk id like
dakshina-kannada:belthangady); they always win and this script never touches that file.

Outputs: ml/data/village_names_kn.csv   village_id, name_kn, source (osm | ai), score
         ml/data/taluk_names_kn.csv     taluk_id, name_kn, source, score
The server picks up new names on its own (no restart needed).

Run from the project root:
    python ml/scripts/fetch_kannada_names.py                 # both steps (AI step needs GEMINI_API_KEY in .env)
    python ml/scripts/fetch_kannada_names.py --osm-only
    python ml/scripts/fetch_kannada_names.py --ai-only --limit 200     # try the AI step on 200 villages first
"""
import argparse
import csv
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import areas, config, kannada  # noqa: E402

RAW = ROOT / "ml" / "data" / "raw" / "osm_places_ka.json"
DROPPED = ROOT / "ml" / "data" / "raw" / "kannada_dropped.csv"     # what the checks refused, and why (last run)
SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
QUERY = """
[out:json][timeout:600];
area["ISO3166-2"="IN-KA"]["admin_level"="4"]->.ka;
node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|locality|isolated_dwelling)$"](area.ka);
out body qt;
"""
NEAR_KM = 3.0
OSM_MIN = 0.75          # unrelated name pairs reach this < 1% of the time, and only nearby places are compared
AI_MIN = 0.60           # the AI was asked about this exact village; below this it is a different word
TALUK_MIN = 0.85
BATCH = 100
ALLOWED = re.compile(r"^[ಀ-೿ ()\-.]+$")
# Census codes after town names (municipal corporation, town council, outgrowth, census town ...): not part of the name
CENSUS_CODES = {"mc", "cmc", "tmc", "tp", "nac", "nmct", "mp", "og", "ct", "(og)", "(ct)", "(rural)", "rural"}
FIELDS = {"village": ["village_id", "name_kn", "source", "score"], "taluk": ["taluk_id", "name_kn", "source", "score"]}
SCHEMA = {"type": "object", "properties": {"names": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "kn": {"type": "string"}}, "required": ["id", "kn"]}}},
    "required": ["names"]}


# ---------- files ----------

def load(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r[key]: r for r in csv.DictReader(f) if r.get(key)}


def save(path: Path, rows: dict[str, dict], kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS[kind])
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in FIELDS[kind]})
    tmp.replace(path)


def core(name: str) -> str:
    """Census name without trailing census codes: "Mangalore Mc" -> "Mangalore", "Kadur Tmc" -> "Kadur"."""
    words = name.split()
    while len(words) > 1 and words[-1].lower() in CENSUS_CODES:
        words.pop()
    return " ".join(words)


def valid(kn: str, en: str, minimum: float) -> tuple[str, float] | None:
    """(clean Kannada name, score) if it is Kannada script and sounds like the English spelling."""
    kn = kannada.clean(kn)
    if not kn or not ALLOWED.match(kn) or not kannada.has_kannada(kn):
        return None
    score = max(kannada.sounds_like(kn, en), kannada.sounds_like(kn, core(en)))
    return (kn, round(score, 2)) if score >= minimum else None


# ---------- step 1: OpenStreetMap ----------

def parse_places(elements: list[dict]) -> list[dict]:
    """Place nodes that have a Kannada name (name:kn, or a name written in Kannada) and a position."""
    out = []
    for e in elements:
        tags = e.get("tags") or {}
        if "lat" not in e or "lon" not in e:
            continue
        kn = tags.get("name:kn") or (tags.get("name") if kannada.has_kannada(tags.get("name")) else None)
        if kn:
            out.append({"lat": e["lat"], "lon": e["lon"], "place": tags.get("place"), "kn": kn,
                        "name": tags.get("name:en") or tags.get("name")})
    return out


def fetch_osm(refresh: bool) -> list[dict]:
    if RAW.exists() and not refresh:
        print(f"using saved OpenStreetMap places ({RAW.relative_to(ROOT)}; --refresh to download again)")
        return json.loads(RAW.read_text(encoding="utf-8"))
    for url in SERVERS:
        for attempt in range(1, 3):
            try:
                print(f"asking {url} for Karnataka's places (attempt {attempt}) ... this can take a few minutes")
                r = requests.post(url, data={"data": QUERY}, timeout=900,
                                  headers={"User-Agent": "disaster-ai student project (Kannada village names)"})
                if r.status_code in (429, 502, 503, 504):
                    print(f"  busy ({r.status_code}); waiting 60 s")
                    time.sleep(60)
                    continue
                r.raise_for_status()
                places = parse_places(r.json()["elements"])
                RAW.parent.mkdir(parents=True, exist_ok=True)
                RAW.write_text(json.dumps(places, ensure_ascii=False), encoding="utf-8")
                return places
            except (requests.RequestException, ValueError, KeyError) as err:
                print(f"  failed: {type(err).__name__}: {str(err)[:120]}")
                time.sleep(10)
    raise SystemExit("All Overpass servers failed. Try again later, or run with --ai-only.")


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    return math.hypot(a_lat - b_lat, (a_lon - b_lon) * math.cos(math.radians(a_lat))) * 111.32


def match_osm(villages: list[dict], places: list[dict]) -> dict[str, tuple[str, float]]:
    """{village_id: (kn, score)} for villages with a nearby OSM place whose Kannada name sounds like theirs."""
    step = 0.05
    grid = defaultdict(list)
    for p in places:
        grid[(int(p["lat"] // step), int(p["lon"] // step))].append(p)
    found = {}
    for v in villages:
        gy, gx = int(v["lat"] // step), int(v["lon"] // step)
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for p in grid.get((gy + dy, gx + dx), ()):
                    d = km(v["lat"], v["lon"], p["lat"], p["lon"])
                    if d > NEAR_KM:
                        continue
                    ok = valid(p["kn"], v["name"], OSM_MIN)
                    if ok and (best is None or (ok[1], -d) > (best[1], -best[2])):
                        best = (ok[0], ok[1], d)
        if best:
            found[v["village_id"]] = (best[0], best[1])
    return found


def match_taluks(a, places: list[dict]) -> dict[str, tuple[str, float]]:
    """A taluk is named after its headquarters town: the biggest OSM place in its squares that sounds like it."""
    rank = {"city": 0, "town": 1, "suburb": 2, "village": 3}
    by_cell = defaultdict(list)
    for p in places:
        by_cell[f"{round((p['lat'] - 6.5) / 0.25) * 0.25 + 6.5:.2f}_{round((p['lon'] - 66.5) / 0.25) * 0.25 + 66.5:.2f}"].append(p)
    found = {}
    for tid, t in a.taluks.items():
        best = None
        for c in t.get("cells", ()):
            for p in by_cell.get(c, ()):
                for en in {t["name"], t.get("census_name") or t["name"]}:
                    ok = valid(p["kn"], en, TALUK_MIN)
                    if ok and (best is None or (rank.get(p["place"], 9), -ok[1]) < (best[2], -best[1])):
                        best = (ok[0], ok[1], rank.get(p["place"], 9))
        if best:
            found[tid] = (best[0], best[1])
    return found


# ---------- step 2: Gemini ----------

def find_names(obj):
    """The [{"id","kn"}] list anywhere in a response envelope (text or parsed JSON)."""
    if isinstance(obj, dict):
        if isinstance(obj.get("names"), list):
            return obj["names"]
        for v in obj.values():
            if (got := find_names(v)) is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            if (got := find_names(v)) is not None:
                return got
    elif isinstance(obj, str) and '"names"' in obj:
        try:
            return find_names(json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", obj.strip())))
        except json.JSONDecodeError:
            return None
    return None


def prompt_for(items: list[dict], examples: list[dict] | None = None) -> str:
    rows = [{"id": i["id"], "name": i["name"], "kind": i["kind"], "taluk": i["taluk"], "district": i["district"]}
            for i in items]
    shown = ""
    if examples:
        shown = ("\nHow nearby villages in the same taluks are spelled locally (from OpenStreetMap). Follow the same "
                 "spelling habits (ಳ or ಲ, long or short vowels, ಹಳ್ಳಿ / ಹಳ್ಳ, final ು, ಕೊಪ್ಪ, ಪುರ ...):\n"
                 + "\n".join(f"{e['name']} ({e['taluk']}) -> {e['kn']}" for e in examples) + "\n")
    return f"""These are villages and taluks in Karnataka, India, spelled in English as in the Census of India 2011.
For each, give its name in Kannada script exactly as it is written on Karnataka government records and village
signboards (for example "Beltangadi" -> "ಬೆಳ್ತಂಗಡಿ", "Ujre" -> "ಉಜಿರೆ", "Hosahalli" -> "ಹೊಸಹಳ್ಳಿ").
Use the common local spelling, not a letter-by-letter transliteration. Keep words in brackets in brackets.
Leave out census codes at the end of town names (Mc, Cmc, Tmc, Tp, Nac, Nmct, Mp, Og, Ct, Rural).
Kannada script only. Return every id once.
{shown}
{json.dumps(rows, ensure_ascii=False)}

Return JSON: {{"names": [{{"id": "...", "kn": "..."}}]}}"""


def ask_gemini(items: list[dict], examples: list[dict] | None = None) -> list[dict]:
    """Names from the main model, or the backup if it is busy; ask_gemini.last_model says which answered."""
    from backend.app.services.alert_drafter import BUSY, _call_model
    models = [config.GEMINI_MODEL] + ([config.GEMINI_FALLBACK_MODEL]
                                      if config.GEMINI_FALLBACK_MODEL not in ("", config.GEMINI_MODEL) else [])
    errors = []
    for model in models:
        reply = _call_model(model, prompt_for(items, examples), schema=SCHEMA, timeout=ANSWER_TIMEOUT_S)
        if reply.status == 200:
            names = find_names(reply.data if reply.data is not None else reply.text)
            if names is None:
                errors.append(f"{model}: no names list in the answer")
                continue
            ask_gemini.last_model = model
            return names
        errors.append(f"{model} HTTP {reply.status}: {reply.text[:160]}")
        if reply.status not in BUSY and reply.status != 0:
            break
    raise RuntimeError(" | ".join(errors))


EXAMPLES_PER_TALUK = 25
EXAMPLES_MAX = 60


def osm_examples(a, v_out: dict) -> dict[str, list[dict]]:
    """{taluk_id: [{"id", "name", "taluk", "kn"}]} for villages whose Kannada name came from OpenStreetMap."""
    out = defaultdict(list)
    for vid, r in v_out.items():
        v = a.villages.get(vid)
        if v and r["source"] == "osm":
            out[v["taluk_id"]].append({"id": vid, "name": v["name"], "taluk": v["taluk"], "kn": r["name_kn"]})
    return out


def examples_for(batch: list[dict], by_taluk: dict, exclude: set = frozenset()) -> list[dict]:
    """Local spelling examples for a batch: per taluk in it, OSM-named villages whose names end like the batch's
    names first (-halli, -koppa, -pura teach the most), never the villages being asked about."""
    import random
    picked = []
    for tid in dict.fromkeys(i.get("taluk_id") for i in batch if i.get("taluk_id")):
        endings = {core(i["name"]).lower()[-4:] for i in batch if i.get("taluk_id") == tid}
        pool = [e for e in by_taluk.get(tid, []) if e["id"] not in exclude]
        random.Random(tid).shuffle(pool)
        pool.sort(key=lambda e: core(e["name"]).lower()[-4:] not in endings)      # matching endings first
        picked += pool[:EXAMPLES_PER_TALUK]
    return picked[:EXAMPLES_MAX]


ANSWER_TIMEOUT_S = 180


def ask_in_parts(batch: list[dict], examples_of=None) -> list[dict]:
    """ask_gemini, but a batch the model can't answer in time is split in half and asked again (down to 10 names).
    Slower 'thinking' models answer 100 names too slowly; 25 or 50 at a time works."""
    try:
        return ask_gemini(batch, examples_of(batch)) if examples_of else ask_gemini(batch)
    except RuntimeError as err:
        if "no answer within" not in str(err) or len(batch) <= 10:
            raise
        half = len(batch) // 2
        print(f"    {len(batch)} names took too long; asking {half} + {len(batch) - half}")
        return ask_in_parts(batch[:half], examples_of) + ask_in_parts(batch[half:], examples_of)


def run_ai(todo: list[dict], villages_out: dict, taluks_out: dict, pause: float,
           examples_by_taluk: dict | None = None) -> None:
    if not config.GEMINI_API_KEY:
        print("AI step skipped: no GEMINI_API_KEY in .env")
        return
    print(f"AI step: {len(todo)} names in batches of {BATCH} (about {math.ceil(len(todo) / BATCH)} requests)")
    dropped = []
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            answers = ask_in_parts(batch, (lambda b: examples_for(b, examples_by_taluk)) if examples_by_taluk else None)
        except RuntimeError as err:
            print(f"  stopped at {start}/{len(todo)}: {str(err)[:300]}")
            print("  (if that says quota/429: the free daily limit is used up. Run again tomorrow; it continues here.)")
            break
        by_id = {i["id"]: i for i in batch}
        answered = set()
        for ans in answers:
            item = by_id.get(str(ans.get("id")))
            if not item:
                continue
            answered.add(item["id"])
            kn = str(ans.get("kn", ""))
            ok = valid(kn, item["name"], AI_MIN)
            if not ok:
                clean = kannada.clean(kn)
                why = ("not Kannada script" if not kannada.has_kannada(clean) else
                       "other characters" if not ALLOWED.match(clean) else
                       f"sounds different ({kannada.sounds_like(clean, core(item['name'])):.2f})")
                dropped.append({"id": item["id"], "name": item["name"], "taluk": item["taluk"], "answer": kn, "why": why})
                continue
            row = {"name_kn": ok[0], "source": "ai-local" if examples_by_taluk else "ai", "score": ok[1]}
            if item["kind"] == "taluk":
                taluks_out[item["id"]] = {"taluk_id": item["id"], **row}
            else:
                villages_out[item["id"]] = {"village_id": item["id"], **row}
        dropped += [{"id": i["id"], "name": i["name"], "taluk": i["taluk"], "answer": "", "why": "no answer for this id"}
                    for i in batch if i["id"] not in answered]
        save(config.VILLAGE_NAMES_KN_CSV, villages_out, "village")       # after every batch: safe to stop any time
        save(config.TALUK_NAMES_KN_CSV, taluks_out, "taluk")
        DROPPED.parent.mkdir(parents=True, exist_ok=True)
        with open(DROPPED, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "name", "taluk", "answer", "why"])
            w.writeheader()
            w.writerows(dropped)
        print(f"  {min(start + BATCH, len(todo))}/{len(todo)} asked, {len(dropped)} answers dropped by the checks so far")
        time.sleep(pause)


# ---------- how good are the AI spellings? ----------

REPORT = ROOT / "ml" / "reports" / "kannada_names.md"
RUNS = ROOT / "ml" / "reports" / "kannada_names_runs.md"      # one line per --eval run, to compare setups


def same_letters(a: str, b: str) -> bool:
    """Equal apart from spaces, dots and dashes ("ಹುಬ್ಬಳ್ಳಿ-ಧಾರವಾಡ" = "ಹುಬ್ಬಳ್ಳಿ ಧಾರವಾಡ")."""
    strip = lambda s: re.sub(r"[\s.\-()]", "", kannada.clean(s))
    return strip(a) == strip(b)


def evaluate(sample: list[dict], answers: dict[str, str]) -> dict:
    """Compare AI answers with the OpenStreetMap names of the same villages (mappers' spelling as the reference)."""
    rows = []
    for v in sample:
        ai = answers.get(v["village_id"], "")
        ok = valid(ai, v["name"], AI_MIN)
        rows.append({**v, "ai": kannada.clean(ai), "exact": kannada.clean(ai) == v["osm"],
                     "letters": same_letters(ai, v["osm"]), "passed": bool(ok)})
    n = len(rows) or 1
    passed = [r for r in rows if r["passed"]]
    return {"n": len(rows),
            "exact": sum(r["exact"] for r in rows) / n,
            "letters": sum(r["letters"] for r in rows) / n,
            "passed": len(passed) / n,
            "passed_and_same": sum(r["letters"] for r in passed) / (len(passed) or 1),
            "refused_but_same": sum(r["letters"] and not r["passed"] for r in rows),
            "differences": [r for r in rows if not r["letters"]]}


def write_eval(res: dict, setup: str) -> None:
    lines = [
        "# How good are the AI-spelled Kannada village names?", "",
        f"Gemini ({setup}) was asked, with the same prompt as for real, for {res['n']} randomly chosen villages that "
        "already have a Kannada name in OpenStreetMap. The mappers' spelling is the reference (it can have mistakes "
        "too, and some villages have two accepted spellings).", "",
        "| Measure | Result |", "|---|---|",
        f"| Same letters as OpenStreetMap (ignoring spaces, dots, dashes) | **{res['letters']:.0%}** |",
        f"| Exactly identical | {res['exact']:.0%} |",
        f"| Passed our automatic \"sounds like the census name\" check | {res['passed']:.0%} |",
        f"| Of those that passed, same letters as OpenStreetMap | {res['passed_and_same']:.0%} |",
        f"| Refused by the check although they were right | {res['refused_but_same']} |", "",
        "The check catches answers that are a different word; it cannot catch small spelling differences "
        "(ಳ vs ಲ, long vs short vowels), which is what most of the remaining differences are. That is why AI names are "
        "marked \"(AI)\" on the dashboard and can be corrected in ml/data/name_kn_fixes.csv.", "",
        "## Differences (first 25)", "", "| Census name | Taluk | OpenStreetMap | AI | Passed check |", "|---|---|---|---|---|"]
    for r in res["differences"][:25]:
        lines.append(f"| {r['name']} | {r['taluk']} | {r['osm']} | {r['ai'] or '(no answer)'} | {'yes' if r['passed'] else 'no'} |")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_eval(a, v_out: dict, n: int, use_examples: bool = True) -> None:
    import random
    if not config.GEMINI_API_KEY:
        raise SystemExit("--eval needs GEMINI_API_KEY in .env")
    osm = [vid for vid, r in v_out.items() if r["source"] == "osm" and vid in a.villages]
    random.Random(7).shuffle(osm)
    sample = [{**{k: a.villages[vid][k] for k in ("village_id", "name", "taluk", "taluk_id", "district")},
               "osm": v_out[vid]["name_kn"]} for vid in osm[:n]]
    sample.sort(key=lambda v: v["taluk_id"])            # batches by taluk, like the real run with examples
    by_taluk = osm_examples(a, v_out) if use_examples else None
    hidden = {v["village_id"] for v in sample}           # the test villages are never shown as examples
    answers, models = {}, set()
    for start in range(0, len(sample), BATCH):
        batch = [{"id": v["village_id"], "name": v["name"], "kind": "village", "taluk": v["taluk"],
                  "taluk_id": v["taluk_id"], "district": v["district"]} for v in sample[start:start + BATCH]]
        got = ask_in_parts(batch, (lambda b: examples_for(b, by_taluk, hidden)) if by_taluk else None)
        models.add(ask_gemini.last_model)
        for ans in got:
            answers[str(ans.get("id"))] = str(ans.get("kn", ""))
        print(f"  {min(start + BATCH, len(sample))}/{len(sample)} asked")
        time.sleep(2)
    res = evaluate(sample, answers)
    setup = f"{' + '.join(sorted(models))}, {'with' if by_taluk else 'without'} local examples"
    write_eval(res, setup)
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    new = not RUNS.exists()
    with open(RUNS, "a", encoding="utf-8") as f:
        if new:
            f.write("| Date | Setup | Villages | Same letters | Exact | Passed check |\n|---|---|---|---|---|---|\n")
        f.write(f"| {date.today()} | {setup} | {res['n']} | {res['letters']:.0%} | {res['exact']:.0%} | {res['passed']:.0%} |\n")
    print(f"\n[{setup}] AI spelling vs OpenStreetMap on {res['n']} villages: same letters {res['letters']:.0%}, "
          f"exact {res['exact']:.0%}, passed the check {res['passed']:.0%} (of those, same letters {res['passed_and_same']:.0%})")
    print(f"saved {REPORT.relative_to(ROOT)} (nothing in the names files was changed)")


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--osm-only", action="store_true")
    ap.add_argument("--ai-only", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="download OpenStreetMap places again")
    ap.add_argument("--limit", type=int, default=0, help="AI step: at most this many names (to try it out)")
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between AI requests (free tier limits)")
    ap.add_argument("--eval", type=int, default=0, metavar="N",
                    help="measure AI spelling on N villages that have an OpenStreetMap name; changes no names")
    ap.add_argument("--no-examples", action="store_true",
                    help="don't show Gemini local OpenStreetMap spellings (the old way; for comparing with --eval)")
    ap.add_argument("--respell", action="store_true",
                    help="ask again for every AI-spelled village, with local examples; OpenStreetMap names are kept")
    args = ap.parse_args()

    a = areas.Areas(config.VILLAGES_CSV, config.AREAS_JSON)             # census names only, nothing merged in
    villages = list(a.villages.values())
    v_out = load(config.VILLAGE_NAMES_KN_CSV, "village_id")
    t_out = load(config.TALUK_NAMES_KN_CSV, "taluk_id")

    if args.eval:
        run_eval(a, v_out, args.eval, use_examples=not args.no_examples)
        return

    if args.respell:                                     # re-spell AI names only; a refused answer keeps the old name
        todo = [{"id": vid, "name": a.villages[vid]["name"], "kind": "village", "taluk": a.villages[vid]["taluk"],
                 "taluk_id": a.villages[vid]["taluk_id"], "district": a.villages[vid]["district"]}
                for vid, r in v_out.items() if r["source"] == "ai" and vid in a.villages]
        todo.sort(key=lambda i: i["taluk_id"])
        if args.limit:
            todo = todo[:args.limit]
        run_ai(todo, v_out, t_out, args.pause, None if args.no_examples else osm_examples(a, v_out))

    if not args.ai_only and not args.respell:
        places = fetch_osm(args.refresh)
        print(f"{len(places)} OpenStreetMap places in Karnataka have a Kannada name; matching ...")
        for vid, (kn, score) in match_osm(villages, places).items():
            v_out[vid] = {"village_id": vid, "name_kn": kn, "source": "osm", "score": score}   # OSM beats AI
        for tid, (kn, score) in match_taluks(a, places).items():
            t_out[tid] = {"taluk_id": tid, "name_kn": kn, "source": "osm", "score": score}
        save(config.VILLAGE_NAMES_KN_CSV, v_out, "village")
        save(config.TALUK_NAMES_KN_CSV, t_out, "taluk")
        n_osm = sum(r["source"] == "osm" for r in v_out.values())
        print(f"OpenStreetMap: {n_osm} villages and {sum(r['source'] == 'osm' for r in t_out.values())} taluks named")

    if not args.osm_only and not args.respell:
        todo = [{"id": tid, "name": t["name"], "kind": "taluk", "taluk": t["name"], "district": t["district"]}
                for tid, t in a.taluks.items() if tid not in t_out]
        todo += [{"id": v["village_id"], "name": v["name"], "kind": "village", "taluk": v["taluk"],
                  "taluk_id": v["taluk_id"], "district": v["district"]}
                 for v in sorted(villages, key=lambda v: -v["population"]) if v["village_id"] not in v_out]
        if args.limit:
            todo = todo[:args.limit]
        run_ai(todo, v_out, t_out, args.pause, None if args.no_examples else osm_examples(a, v_out))

    by_src = defaultdict(int)
    for r in v_out.values():
        by_src[r["source"]] += 1
    have_pop = sum(v["population"] for v in villages if v["village_id"] in v_out)
    total_pop = sum(v["population"] for v in villages) or 1
    print(f"\nKannada names: {len(v_out)}/{len(villages)} villages ({dict(by_src)}), covering "
          f"{have_pop / total_pop:.0%} of village population; {len(t_out)}/{len(a.taluks)} taluks")
    for v in sorted(villages, key=lambda v: -v["population"])[:8]:
        r = v_out.get(v["village_id"])
        print(f"  {v['name']:<22} {v['taluk']:<14} {r['name_kn'] if r else '-':<18} {r['source'] if r else ''}")
    print(f"saved {config.VILLAGE_NAMES_KN_CSV.relative_to(ROOT)} and {config.TALUK_NAMES_KN_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
