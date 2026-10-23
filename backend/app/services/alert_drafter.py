"""
Draft a bilingual (Kannada + English) warning for one village.

1. Ask Gemini to write it from the facts the risk engine produced, as JSON {"kn": ..., "en": ...}.
2. Check the draft before trusting it:
     - both messages present and short enough for a phone screen / SMS
     - the Kannada message is actually in Kannada script
     - the English message names the village
     - every number in it is one we gave the model (no invented rainfall,
       phone numbers or shelter capacities)
3. If there's no API key, the call fails, or any check fails, use a fixed
   template instead, and record why. A person approves every alert either way.
"""
import json
import re
import time

import requests

from .. import config

MAX_CHARS = {"en": 320, "kn": 420}  # Kannada script needs more characters for the same message
KANNADA = re.compile(r"[ಀ-೿]")

SCHEMA = {
    "type": "object",
    "properties": {
        "kn": {"type": "string", "description": "Warning in Kannada script"},
        "en": {"type": "string", "description": "The same warning in simple English"},
    },
    "required": ["kn", "en"],
}


# ---------- facts ----------

def facts_for(risk: dict, village: dict) -> dict:
    """The only information the model is allowed to use."""
    return {
        "village_en": risk["name"],
        "village_kn": village.get("name_kn") or risk["name"],
        "district": risk["district"],
        "level": risk["level"],
        "rain_last_3_days_mm": int(round(risk["past_3d_mm"])),
        "rain_next_3_days_mm": int(round(risk["forecast_3d_mm"])),
        "main_cause": "forecast" if risk["forecast_3d_mm"] >= risk["past_3d_mm"] else "recent rain",
        "emergency_number": config.EMERGENCY_NUMBER,
    }


def build_prompt(f: dict) -> str:
    return f"""You write emergency warnings for villagers in Coastal and Malnad Karnataka.
Write ONE short flood and landslide warning for the village below, in Kannada and in English.

FACTS (use only these; do not add anything else):
{json.dumps(f, ensure_ascii=False, indent=2)}

RULES
- Kannada: simple, spoken style that a villager in {f['district']} understands. Kannada script only.
- English: the same message in plain English.
- Each message at most 3 short sentences.
- Mention the village name and the rain amount for the main cause.
- Tell people to stay away from rivers, streams and steep slopes, and to follow the
  Gram Panchayat's instructions about moving to a shelter.
- End with the emergency number {f['emergency_number']}.
- Do NOT invent shelter names, phone numbers, dates, times, or any other numbers.
- Calm and clear. No panic words, no emojis.

Return JSON: {{"kn": "...", "en": "..."}}"""


# ---------- Gemini ----------

def _find_json_draft(obj):
    """Search any response envelope for a JSON string or object with 'kn' and 'en'.
    The Interactions API returns text under a field like output_text/outputs; rather than
    depend on one exact layout, look everywhere."""
    if isinstance(obj, dict):
        if isinstance(obj.get("kn"), str) and isinstance(obj.get("en"), str):
            return obj
        for v in obj.values():
            found = _find_json_draft(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_json_draft(v)
            if found:
                return found
    elif isinstance(obj, str) and "kn" in obj and "en" in obj:
        text = obj.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # strip ``` fences if present
        try:
            return _find_json_draft(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            return None
    return None


BUSY = (429, 500, 503)  # rate-limited or overloaded: worth retrying / trying another model


class Reply:
    """What came back from one model: an HTTP status (0 = no answer in time) and the body."""
    def __init__(self, status: int, text: str, data=None):
        self.status, self.text, self.data = status, text, data


def _post(body: dict) -> Reply:
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(config.GEMINI_URL, headers=headers, json=body, timeout=config.GEMINI_TIMEOUT_S)
    except (requests.Timeout, requests.ConnectionError) as err:
        return Reply(0, f"no answer within {config.GEMINI_TIMEOUT_S}s ({type(err).__name__})")
    try:
        data = resp.json()
    except ValueError:
        data = None
    return Reply(resp.status_code, resp.text, data)


def _call_model(model: str, prompt: str) -> Reply:
    """One model. Retries briefly when it answers 'busy'; gives up on it at once if it
    doesn't answer at all (an overloaded model rarely recovers within seconds)."""
    body = {
        "model": model,
        "input": prompt,
        "response_format": {"type": "text", "mime_type": "application/json", "schema": SCHEMA},
        # A 3-sentence warning needs no long reasoning; low thinking answers much faster.
        "generation_config": {"thinking_level": "low"},
    }
    reply = Reply(0, "not called")
    for attempt in range(config.GEMINI_BUSY_RETRIES + 1):
        reply = _post(body)
        if reply.status == 400 and len(body) > 2:
            # The model rejected an optional setting: retry with only the model and prompt.
            body = {"model": model, "input": prompt}
            reply = _post(body)
        if reply.status not in BUSY:
            break  # success, a real error, or a timeout (0): stop retrying this model
        if attempt < config.GEMINI_BUSY_RETRIES:
            time.sleep(config.GEMINI_RETRY_WAIT_S * (attempt + 1))
    return reply


def call_gemini(prompt: str) -> dict:
    """Try the main model, then the backup model if the main one is busy or silent.
    Returns {"kn", "en", "model"}."""
    models = [config.GEMINI_MODEL]
    if config.GEMINI_FALLBACK_MODEL and config.GEMINI_FALLBACK_MODEL != config.GEMINI_MODEL:
        models.append(config.GEMINI_FALLBACK_MODEL)
    errors = []
    for model in models:
        reply = _call_model(model, prompt)
        if reply.status == 200:
            draft = _find_json_draft(reply.data if reply.data is not None else reply.text)
            if not draft:
                raise RuntimeError(f"No kn/en JSON found in {model} response: {reply.text[:300]}")
            return {"kn": draft["kn"].strip(), "en": draft["en"].strip(), "model": model}
        label = "timeout" if reply.status == 0 else f"HTTP {reply.status}"
        errors.append(f"{model} {label}: {reply.text[:200]}")
        if reply.status not in BUSY and reply.status != 0:
            break  # a real error (bad key, bad request): another model won't help
    raise RuntimeError(" | ".join(errors))


# ---------- checks ----------

def check_draft(draft: dict, f: dict) -> list[str]:
    """Return a list of problems; empty means the draft passed."""
    problems = []
    for lang in ("kn", "en"):
        text = draft.get(lang, "")
        if not text:
            problems.append(f"{lang} message is empty")
        elif len(text) > MAX_CHARS[lang]:
            problems.append(f"{lang} message too long ({len(text)} > {MAX_CHARS[lang]} chars)")
    if draft.get("kn") and not KANNADA.search(draft["kn"]):
        problems.append("kn message has no Kannada script")
    if draft.get("en") and f["village_en"].lower() not in draft["en"].lower():
        problems.append("en message does not name the village")
    allowed = {str(f["rain_last_3_days_mm"]), str(f["rain_next_3_days_mm"]), f["emergency_number"], "3"}
    for lang in ("kn", "en"):
        for n in re.findall(r"\d+", draft.get(lang, "")):
            n = str(int(n))  # \d also matches Kannada digits (೧೧೨); int() turns them into 112
            if n not in allowed:
                problems.append(f"{lang} message contains a number not in the facts: {n}")
    return problems


# ---------- template ----------

def template_draft(f: dict) -> dict:
    if f["main_cause"] == "forecast":
        rain_en = f"{f['rain_next_3_days_mm']} mm of rain is expected in the next 3 days."
        rain_kn = f"ಮುಂದಿನ 3 ದಿನಗಳಲ್ಲಿ {f['rain_next_3_days_mm']} ಮಿ.ಮೀ. ಮಳೆ ನಿರೀಕ್ಷಿಸಲಾಗಿದೆ."
    else:
        rain_en = f"{f['rain_last_3_days_mm']} mm of rain has fallen in the last 3 days."
        rain_kn = f"ಕಳೆದ 3 ದಿನಗಳಲ್ಲಿ {f['rain_last_3_days_mm']} ಮಿ.ಮೀ. ಮಳೆಯಾಗಿದೆ."
    en = (f"Warning for {f['village_en']}: high risk of floods and landslides. {rain_en} "
          f"Stay away from rivers, streams and steep slopes, and move to the nearest shelter "
          f"if the Gram Panchayat asks. Emergency: {f['emergency_number']}.")
    kn = (f"ಎಚ್ಚರಿಕೆ: {f['village_kn']} ಪ್ರದೇಶದಲ್ಲಿ ಪ್ರವಾಹ ಮತ್ತು ಭೂಕುಸಿತದ ಅಪಾಯ ಹೆಚ್ಚಾಗಿದೆ. {rain_kn} "
          f"ನದಿ, ಹಳ್ಳ ಮತ್ತು ಕಡಿದಾದ ಇಳಿಜಾರುಗಳಿಂದ ದೂರವಿರಿ. ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಸೂಚಿಸಿದರೆ ಹತ್ತಿರದ "
          f"ಆಶ್ರಯ ಕೇಂದ್ರಕ್ಕೆ ತೆರಳಿ. ತುರ್ತು ಸಂಖ್ಯೆ: {f['emergency_number']}.")
    return {"kn": kn, "en": en}


# ---------- main entry ----------

def draft_alert(risk: dict, village: dict) -> dict:
    """Returns {"kn", "en", "source": "gemini"|"template", "note"}."""
    f = facts_for(risk, village)
    if not config.GEMINI_API_KEY:
        return {**template_draft(f), "source": "template", "note": "no GEMINI_API_KEY set"}
    try:
        draft = call_gemini(build_prompt(f))
    except Exception as err:
        return {**template_draft(f), "source": "template", "note": f"Gemini failed: {err}"[:500]}
    problems = check_draft(draft, f)
    if problems:
        return {**template_draft(f), "source": "template",
                "note": f"{draft['model']} draft rejected: " + "; ".join(problems)}
    return {"kn": draft["kn"], "en": draft["en"], "source": "gemini", "note": draft["model"]}
