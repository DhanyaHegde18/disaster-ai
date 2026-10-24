"""Tests for alert drafting, with Gemini mocked. Run: pytest backend/tests -v"""
import json

import pytest

from backend.app import config
from backend.app.services import alert_drafter as d

RISK = {"taluk_id": "dakshina-kannada:belthangady", "name": "Belthangady", "district": "Dakshina Kannada",
        "district_kn": "ದಕ್ಷಿಣ ಕನ್ನಡ", "level": "HIGH", "past_3d_mm": 40.4, "forecast_3d_mm": 251.6,
        "reasons": [], "daily_mm": [], "places": ["Ujre", "Dharmasthala"]}
FACTS = d.facts_for(RISK)

GOOD = {"kn": "ಬೆಳ್ತಂಗಡಿ ತಾಲ್ಲೂಕು (ಉಜಿರೆ, ಧರ್ಮಸ್ಥಳ): ಮುಂದಿನ 3 ದಿನಗಳಲ್ಲಿ 252 ಮಿ.ಮೀ. ಮಳೆ. ನದಿಗಳಿಂದ ದೂರವಿರಿ. ತುರ್ತು ಸಂಖ್ಯೆ 112.",
        "en": "Belthangady taluk (Ujre, Dharmasthala): 252 mm of rain expected in the next 3 days. "
              "Stay away from rivers. Emergency 112."}


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._p


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "main-model")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "backup-model")
    monkeypatch.setattr(d.time, "sleep", lambda s: None)  # don't actually wait between retries


def test_facts_are_rounded_and_cause_detected():
    assert FACTS["rain_next_3_days_mm"] == 252
    assert FACTS["main_cause"] == "forecast"
    assert FACTS["district_kn"] == "ದಕ್ಷಿಣ ಕನ್ನಡ" and FACTS["villages_most_affected"] == ["Ujre", "Dharmasthala"]


def test_template_names_taluk_and_villages(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    out = d.draft_alert(RISK)
    assert "Belthangady taluk (Ujre, Dharmasthala and nearby villages)" in out["en"]
    assert "ದಕ್ಷಿಣ ಕನ್ನಡ ಜಿಲ್ಲೆಯ Belthangady ತಾಲ್ಲೂಕಿನಲ್ಲಿ" in out["kn"]


def test_draft_must_name_the_taluk():
    assert any("taluk" in p for p in d.check_draft(dict(GOOD, en="Heavy rain expected. Call 112."), FACTS))


def test_template_used_without_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    out = d.draft_alert(RISK)
    assert out["source"] == "template" and "no GEMINI_API_KEY" in out["note"]
    assert d.check_draft(out, FACTS) == []          # the template itself passes every check


def test_good_gemini_draft_accepted(monkeypatch, with_key):
    # Response wrapped in an envelope with the JSON as a text string, as the API returns it.
    envelope = {"outputs": [{"type": "text", "text": json.dumps(GOOD, ensure_ascii=False)}]}
    monkeypatch.setattr(d.requests, "post", lambda *a, **k: FakeResp(200, envelope))
    out = d.draft_alert(RISK)
    assert out["source"] == "gemini"
    assert out["en"] == GOOD["en"]


def test_fenced_json_is_parsed(monkeypatch, with_key):
    text = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"
    monkeypatch.setattr(d.requests, "post", lambda *a, **k: FakeResp(200, {"output_text": text}))
    assert d.draft_alert(RISK)["source"] == "gemini"


def test_invented_number_rejected(monkeypatch, with_key):
    bad = dict(GOOD, en=GOOD["en"] + " Shelter at the school holds 500 people.")
    monkeypatch.setattr(d.requests, "post", lambda *a, **k: FakeResp(200, {"output_text": json.dumps(bad)}))
    out = d.draft_alert(RISK)
    assert out["source"] == "template" and "500" in out["note"]


def test_kannada_digits_count_as_numbers():
    draft = dict(GOOD, kn=GOOD["kn"].replace("112", "೧೧೨"))      # ೧೧೨ = 112, allowed
    assert d.check_draft(draft, FACTS) == []
    draft = dict(GOOD, kn=GOOD["kn"] + " ೫೦೦")                       # ೫೦೦ = 500, not allowed
    assert any("500" in p for p in d.check_draft(draft, FACTS))


def test_non_kannada_rejected():
    draft = dict(GOOD, kn="Belthangady warning in English only, 112")
    assert any("Kannada" in p for p in d.check_draft(draft, FACTS))


def test_busy_everywhere_falls_back_to_template(monkeypatch, with_key):
    calls = []

    def busy(url, headers, json, timeout):
        calls.append(json["model"])
        return FakeResp(503, {"error": "high demand"})

    monkeypatch.setattr(d.requests, "post", busy)
    out = d.draft_alert(RISK)
    assert out["source"] == "template" and "503" in out["note"]
    # 1 try + 2 retries on each model, main model first.
    assert calls == ["main-model"] * 3 + ["backup-model"] * 3


def test_busy_main_model_uses_backup(monkeypatch, with_key):
    def post(url, headers, json, timeout):
        if json["model"] == "main-model":
            return FakeResp(503, {"error": "high demand"})
        return FakeResp(200, {"output_text": __import__("json").dumps(GOOD)})

    monkeypatch.setattr(d.requests, "post", post)
    out = d.draft_alert(RISK)
    assert out["source"] == "gemini" and out["note"] == "backup-model"


def test_timeout_moves_straight_to_backup(monkeypatch, with_key):
    calls = []

    def post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "main-model":
            raise d.requests.Timeout("read timed out")
        return FakeResp(200, {"output_text": __import__("json").dumps(GOOD)})

    monkeypatch.setattr(d.requests, "post", post)
    out = d.draft_alert(RISK)
    assert out["source"] == "gemini" and out["note"] == "backup-model"
    assert calls == ["main-model", "backup-model"]   # no waiting retries on a silent model


def test_both_silent_uses_template(monkeypatch, with_key):
    def silent(url, headers, json, timeout):
        raise d.requests.Timeout("read timed out")

    monkeypatch.setattr(d.requests, "post", silent)
    out = d.draft_alert(RISK)
    assert out["source"] == "template"
    assert "main-model timeout" in out["note"] and "backup-model timeout" in out["note"]


def test_low_thinking_requested(monkeypatch, with_key):
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return FakeResp(200, {"output_text": __import__("json").dumps(GOOD)})

    monkeypatch.setattr(d.requests, "post", post)
    d.draft_alert(RISK)
    assert seen["generation_config"] == {"thinking_level": "low"}


def test_bad_key_does_not_try_backup(monkeypatch, with_key):
    calls = []

    def forbidden(url, headers, json, timeout):
        calls.append(json["model"])
        return FakeResp(403, {"error": "API key not valid"})

    monkeypatch.setattr(d.requests, "post", forbidden)
    out = d.draft_alert(RISK)
    assert out["source"] == "template" and "403" in out["note"]
    assert calls == ["main-model"]


def test_retries_without_schema_on_400(monkeypatch, with_key):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append("response_format" in json)
        return FakeResp(400, {}) if len(calls) == 1 else FakeResp(200, {"output_text": __import__("json").dumps(GOOD)})

    monkeypatch.setattr(d.requests, "post", fake_post)
    assert d.draft_alert(RISK)["source"] == "gemini"
    assert calls == [True, False]
