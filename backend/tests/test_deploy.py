"""Running on a server: staff from the OFFICIALS setting, sign-in codes by ntfy, and the database backup."""
import sqlite3
import types

import pytest

from backend.app import auth, config, notify, state_backup
from backend.tests.conftest import BELTHANGADY, app_client


# ---------- staff from settings ----------

def test_seed_officials_from_settings():
    added, problems = auth.seed_officials(
        "9876543210, Ujire GP, gp, Dakshina Kannada, Belthangady\n"
        "9123456780, Red Cross DK, ngo, Dakshina Kannada;"
        " 9000000001, Someone, gp, , Nowhere ;  ")
    assert [(o["name"], o["role"], o.get("taluk_id"), o["district"]) for o in added] == [
        ("Ujire GP", "gp", BELTHANGADY, "Dakshina Kannada"), ("Red Cross DK", "ngo", None, "Dakshina Kannada")]
    assert len(problems) == 1 and "Nowhere" in problems[0] and "not found" in problems[0]


def test_officials_setting_applied_at_start(monkeypatch):
    monkeypatch.setattr(config, "OFFICIALS", "9876543210, Ujire GP, gp, Dakshina Kannada, Belthangady")
    with app_client() as c:
        r = c.post("/auth/request-code", json={"phone": "9876543210"})
        assert r.status_code == 200                                   # registered by the setting


# ---------- sign-in codes by ntfy ----------

@pytest.fixture
def ntfy(monkeypatch):
    monkeypatch.setattr(config, "SMS_PROVIDER", "ntfy")
    monkeypatch.setattr(config, "OTP_DEMO_MODE", False)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "gp-secret")
    sent = []

    def fake_post(url, data, timeout, headers):
        sent.append((url, data.decode("utf-8"), headers))
        return types.SimpleNamespace(status_code=200, text="")
    monkeypatch.setattr(notify.requests, "post", fake_post)
    return sent


def test_staff_code_goes_to_their_topic(ntfy):
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    with app_client() as c:
        r = c.post("/auth/request-code", json={"phone": "9876543210"}).json()
        assert r["sent_by"] == "ntfy" and "demo_code" not in r
        url, text, headers = ntfy[-1]
        assert url.endswith("/gp-secret-dakshina-kannada-belthangady") and headers["Title"] == "Sign-in code"
        code = text.split(": ")[1].split(" ")[0]
        assert c.post("/auth/verify", json={"phone": "9876543210", "code": code}).status_code == 200


def test_villager_code_on_screen_with_ntfy(ntfy):
    with app_client() as c:
        r = c.post("/public/auth/request-code", json={"phone": "9000000001"}).json()
        assert r["sent_by"] == "screen" and len(r["demo_code"]) == 6 and ntfy == []


def test_ntfy_without_topic_is_a_clear_error(ntfy, monkeypatch):
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "")
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    with app_client() as c:
        r = c.post("/auth/request-code", json={"phone": "9876543210"})
        assert r.status_code == 500 and "NTFY_TOPIC_GP" in r.json()["detail"]


# ---------- database backup to a private dataset ----------

class FakeHub:
    def __init__(self, private=True):
        self.private, self.files, self.uploads = private, {}, 0

    def api(self):
        hub = self

        class Api:
            def create_repo(self, repo_id, repo_type, private, exist_ok):
                assert private and repo_type == "dataset"

            def repo_info(self, repo_id, repo_type):
                return types.SimpleNamespace(private=hub.private)

            def list_repo_files(self, repo_id, repo_type):
                return list(hub.files)

            def upload_file(self, path_or_fileobj, path_in_repo, repo_id, repo_type, commit_message):
                hub.files[path_in_repo] = open(path_or_fileobj, "rb").read()
                hub.uploads += 1
        return Api()

    def download(self, repo_id, filename, repo_type, token, local_dir):
        path = f"{local_dir}/{filename}"
        open(path, "wb").write(self.files[filename])
        return path


@pytest.fixture
def hub(monkeypatch):
    h = FakeHub()
    monkeypatch.setattr(config, "STATE_REPO", "someone/disaster-ai-state")
    monkeypatch.setattr(config, "HF_TOKEN", "hf_test")
    monkeypatch.setattr(state_backup, "_api", h.api)
    huggingface_hub = pytest.importorskip("huggingface_hub")      # pip install huggingface_hub
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", h.download)
    monkeypatch.setitem(state_backup.state, "_hash", None)
    monkeypatch.setitem(state_backup.state, "last_error", None)
    return h


def test_backup_off_by_default():
    assert not state_backup.enabled() and state_backup.backup() is False
    assert state_backup.summary().startswith("off")


def test_backup_uploads_only_changes_and_restores(hub):
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    assert state_backup.backup() is True and hub.uploads == 1
    assert state_backup.backup() is False and hub.uploads == 1           # unchanged: no upload
    auth.add_official("9123456780", "Red Cross DK", "ngo", district="Dakshina Kannada")
    assert state_backup.backup() is True and hub.uploads == 2
    config.ALERTS_DB.unlink()                                           # the server restarts with an empty disk
    assert state_backup.restore().startswith("restored")
    with sqlite3.connect(config.ALERTS_DB) as c:
        assert c.execute("SELECT COUNT(*) FROM officials").fetchone()[0] == 2


def test_first_start_has_nothing_to_restore(hub):
    assert state_backup.restore() == "nothing saved yet (first start)"


def test_never_uploads_to_a_public_repo(hub):
    hub.private = False
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    assert state_backup.backup() is False and hub.uploads == 0
    assert "PUBLIC" in state_backup.summary()


def test_health_shows_backup_and_sign_in(hub, ntfy):
    with app_client() as c:
        h = c.get("/health").json()
        assert h["database_backup"].startswith("every 5 min to private dataset someone/disaster-ai-state")
        assert h["sign_in"].startswith("staff codes by ntfy")


def test_unloadable_landslide_model_falls_back_to_rain_rule():
    from backend.app.services import landslide
    landslide.MODEL_FILE.write_bytes(b"not a model")                  # e.g. saved by another scikit-learn version
    landslide.META_FILE.write_text("{}")
    assert landslide.model() is None and landslide.load_error
    with app_client() as c:
        assert "could not be loaded here" in c.get("/health").json()["landslide_model"]
    landslide.load_error = None


# ---------- anyone may sign in (OPEN_SIGNIN) ----------

def guest_sign_in(c, phone="9000012345"):
    r = c.post("/auth/request-code", json={"phone": phone})
    assert r.status_code == 200, r.text
    code = r.json()["demo_code"]                                      # shown on screen
    r = c.post("/auth/verify", json={"phone": phone, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def test_open_signin_off_by_default():
    with app_client() as c:
        assert c.post("/auth/request-code", json={"phone": "9000012345"}).status_code == 403


def test_open_signin_viewer_is_read_only(monkeypatch, ntfy):
    monkeypatch.setattr(config, "OPEN_SIGNIN", "viewer")
    with app_client() as c:
        me = guest_sign_in(c)
        assert me["role"] == "ngo" and me["name"] == "Guest ····2345"
        assert c.get("/risk").status_code == 200                       # sees the risk
        assert c.post("/alerts/generate").status_code == 403           # can't draft or approve
        assert ntfy == []                                              # guest codes go nowhere, only on screen
        assert c.get("/health").json()["open_sign_in"].startswith("ON: any number can sign in as a read-only guest")


def test_open_signin_gp_guest(monkeypatch):
    monkeypatch.setattr(config, "OPEN_SIGNIN", "gp")
    with app_client() as c:
        me = guest_sign_in(c)
        assert me["role"] == "gp" and me["taluk_id"] == BELTHANGADY


def test_registered_staff_still_get_ntfy_codes_with_open_signin(monkeypatch, ntfy):
    monkeypatch.setattr(config, "OPEN_SIGNIN", "viewer")
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    with app_client() as c:
        r = c.post("/auth/request-code", json={"phone": "9876543210"}).json()
        assert r["sent_by"] == "ntfy" and "demo_code" not in r and len(ntfy) == 1


# ---------- risk map sent from elsewhere (forecast API refuses the server) ----------

def make_snapshot(world, high_cell="13.00_75.25"):
    from backend.app.jobs import score_grid
    world.rain(high_cell, past=200)
    snap = score_grid.score_now()
    config.LATEST_RISK_FILE.unlink()                                  # as if computed on another computer
    return snap


def test_snapshot_push_needs_the_token(world, monkeypatch):
    snap = make_snapshot(world)
    with app_client() as c:
        assert c.post("/system/snapshot", json=snap).status_code == 403        # no token set on the server
        monkeypatch.setattr(config, "SNAPSHOT_TOKEN", "s3cret")
        assert c.post("/system/snapshot", json=snap, headers={"X-Snapshot-Token": "nope"}).status_code == 403
        assert c.post("/system/snapshot", json={"cells": []}, headers={"X-Snapshot-Token": "s3cret"}).status_code == 422
        bad = {**snap, "cells": [{**snap["cells"][0], "cell_id": "99.00_99.00"}]}
        assert c.post("/system/snapshot", json=bad, headers={"X-Snapshot-Token": "s3cret"}).status_code == 422


def test_pushed_snapshot_is_used_and_drafts_alerts(world, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOT_TOKEN", "s3cret")
    snap = make_snapshot(world)
    from backend.app.jobs import score_grid

    def refuse(points, past_days=2):
        raise RuntimeError("Open-Meteo limit reached for this server's internet address: Daily API request limit exceeded")
    monkeypatch.setattr(score_grid, "fetch_daily_rain", refuse)
    with app_client() as c:
        r = c.post("/system/snapshot", json=snap, headers={"X-Snapshot-Token": "s3cret"}).json()
        assert r["summary"]["HIGH"] >= 1 and r["alerts_drafted"] == 1
        auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
        from backend.tests.conftest import sign_in
        sign_in(c)
        risk = c.get("/risk").json()
        assert risk["summary"]["HIGH"] == 2 and not risk["stale"]


def test_failed_fetch_is_not_retried_on_every_page_load(world, monkeypatch):
    from backend.app.jobs import score_grid
    from backend.app.routers import risk as risk_router
    calls = []

    def refuse(points, past_days=2):
        calls.append(1)
        raise RuntimeError("429 daily limit")
    snap = make_snapshot(world)
    config.LATEST_RISK_FILE.write_text(__import__("json").dumps({**snap, "generated_at": "2026-01-01T00:00:00+05:30"}))
    monkeypatch.setattr(score_grid, "fetch_daily_rain", refuse)
    first = risk_router._cached_or_fresh()
    second = risk_router._cached_or_fresh()
    assert first["stale"] and second["stale"] and len(calls) == 1 and "429" in second["stale_reason"]


def test_open_meteo_429_minute_waits_daily_gives_up(monkeypatch):
    from backend.app.services import forecast
    slept, replies = [], []

    class Resp:
        def __init__(self, status, reason):
            self.status_code, self._reason, self.text = status, reason, reason

        def json(self):
            return {"error": True, "reason": self._reason} if self.status_code == 429 else [
                {"daily": {"time": ["2026-10-28"], "precipitation_sum": [1.0]}}]

        def raise_for_status(self):
            pass
    monkeypatch.setattr(forecast.time, "sleep", lambda s: slept.append(s))
    seq = [Resp(429, "Minutely API request limit exceeded. Please try again in one minute."), Resp(200, "")]
    monkeypatch.setattr(forecast.requests, "get", lambda url, params, timeout: seq.pop(0))
    assert forecast._get({}) and slept == [61]
    monkeypatch.setattr(forecast.requests, "get", lambda url, params, timeout: Resp(429, "Daily API request limit exceeded."))
    with pytest.raises(RuntimeError, match="Daily API request limit"):
        forecast._get({})
    assert slept == [61]                                              # no pointless waiting for a daily limit


def test_push_job_sends_the_map(world, monkeypatch, capsys):
    from backend.app.jobs import push_snapshot
    sent = {}

    def fake_post(url, json, timeout, headers):
        sent.update(url=url, cells=len(json["cells"]), token=headers["X-Snapshot-Token"])
        return types.SimpleNamespace(status_code=200, text='{"saved": "x"}')
    monkeypatch.setattr(push_snapshot.requests, "post", fake_post)
    monkeypatch.setenv("SERVER_URL", "https://example.onrender.com/")
    monkeypatch.setenv("SNAPSHOT_TOKEN", "s3cret")
    assert push_snapshot.main() == 0
    assert sent == {"url": "https://example.onrender.com/system/snapshot", "cells": 4, "token": "s3cret"}


def test_backup_includes_the_risk_map(hub, world):
    make_snapshot(world)
    from backend.app.jobs import score_grid
    score_grid.score_now()
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    assert state_backup.backup() and set(hub.files) == {"alerts.db", "latest_risk.json"}
    config.LATEST_RISK_FILE.unlink()
    state_backup.restore()
    assert config.LATEST_RISK_FILE.exists()


def test_refused_ntfy_says_why_and_token_is_sent(monkeypatch):
    monkeypatch.setattr(config, "SMS_PROVIDER", "ntfy")
    monkeypatch.setattr(config, "OTP_DEMO_MODE", False)
    monkeypatch.setattr(config, "NTFY_TOPIC_GP", "gp-secret")
    seen = []

    def refuse(url, data, timeout, headers):
        seen.append(headers)
        return types.SimpleNamespace(status_code=429, text='{"error":"limit reached"}',
                                     json=lambda: {"error": "limit reached"})
    monkeypatch.setattr(notify.requests, "post", refuse)
    auth.add_official("9876543210", "Ujire GP", "gp", taluk_id=BELTHANGADY)
    with app_client() as c:
        r = c.post("/auth/request-code", json={"phone": "9876543210"})
        assert r.status_code == 502 and "429" in r.json()["detail"] and "NTFY_TOKEN" in r.json()["detail"]
        assert "Authorization" not in seen[-1]
        monkeypatch.setattr(config, "NTFY_TOKEN", "tk_abc")
        monkeypatch.setattr(config, "OTP_RESEND_S", 0)
        c.post("/auth/request-code", json={"phone": "9876543210"})
        assert seen[-1]["Authorization"] == "Bearer tk_abc"
