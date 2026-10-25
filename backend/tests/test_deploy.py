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
