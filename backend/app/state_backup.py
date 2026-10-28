"""
Keep the database (staff, alerts, family reports, relief centres) safe on a server whose disk is wiped on restart,
like a free Render web service.

  restore()      at start-up: copy alerts.db back from the private dataset repository (if there is one)
  backup()       copy alerts.db to that repository, only if it changed since the last copy
  backup_loop()  backup() every STATE_BACKUP_MIN minutes while the server runs (and once more when it stops)

The repository holds phone numbers, so it is created PRIVATE, and nothing is uploaded to a repository that is public.
Off (does nothing) unless STATE_REPO and HF_TOKEN are set; on a laptop the database simply stays on disk.
"""
import asyncio
import hashlib
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from . import config

FILE = "alerts.db"
SNAPSHOT = "latest_risk.json"   # the last risk map too, so a restarted server has data before the next rain check
state = {"last_backup": None, "last_error": None, "restored": None, "_hash": None, "_snap_hash": None}


def enabled() -> bool:
    return bool(config.STATE_REPO and config.HF_TOKEN)


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=config.HF_TOKEN)


def _private_repo(api) -> bool:
    """Create the dataset repository as private if needed; refuse to use one that is public."""
    api.create_repo(config.STATE_REPO, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(config.STATE_REPO, repo_type="dataset").private:
        state["last_error"] = f"{config.STATE_REPO} is PUBLIC: make it private on huggingface.co (it holds phone numbers)"
        print(f"[backup] {state['last_error']}; not uploading", flush=True)
        return False
    return True


def restore() -> str:
    """Bring back the last saved database. Call before database.init_db()."""
    if not enabled():
        return "off"
    try:
        from huggingface_hub import hf_hub_download
        api = _api()
        if not _private_repo(api):
            return "refused (public repository)"
        if FILE not in api.list_repo_files(config.STATE_REPO, repo_type="dataset"):
            state["restored"] = "nothing saved yet (first start)"
            return state["restored"]
        path = hf_hub_download(config.STATE_REPO, FILE, repo_type="dataset", token=config.HF_TOKEN,
                               local_dir=tempfile.mkdtemp())
        config.ALERTS_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, config.ALERTS_DB)
        state["_hash"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if SNAPSHOT in api.list_repo_files(config.STATE_REPO, repo_type="dataset"):
            snap = hf_hub_download(config.STATE_REPO, SNAPSHOT, repo_type="dataset", token=config.HF_TOKEN,
                                   local_dir=tempfile.mkdtemp())
            config.LATEST_RISK_FILE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snap, config.LATEST_RISK_FILE)
            state["_snap_hash"] = hashlib.sha256(Path(snap).read_bytes()).hexdigest()
        state["restored"] = f"restored at {datetime.now().isoformat(timespec='seconds')}"
        print(f"[backup] database {state['restored']} from {config.STATE_REPO}", flush=True)
    except Exception as err:                       # a failed restore must not stop the server starting
        state["last_error"] = f"restore failed: {type(err).__name__}: {str(err)[:200]}"
        print(f"[backup] {state['last_error']}", flush=True)
    return state["restored"] or "failed"


def backup() -> bool:
    """Upload a consistent copy of the database if it changed. True if uploaded."""
    if not enabled() or not config.ALERTS_DB.exists():
        return False
    tmp = Path(tempfile.mkdtemp()) / FILE
    try:
        src, dst = sqlite3.connect(config.ALERTS_DB), sqlite3.connect(tmp)
        with dst:
            src.backup(dst)                        # safe while the server is writing
        src.close()
        dst.close()
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        snap = config.LATEST_RISK_FILE
        snap_digest = hashlib.sha256(snap.read_bytes()).hexdigest() if snap.exists() else None
        if digest == state["_hash"] and snap_digest == state["_snap_hash"]:
            return False
        api = _api()
        if not _private_repo(api):
            return False
        stamp = datetime.now().isoformat(timespec="minutes")
        if digest != state["_hash"]:
            api.upload_file(path_or_fileobj=str(tmp), path_in_repo=FILE, repo_id=config.STATE_REPO,
                            repo_type="dataset", commit_message=f"database {stamp}")
            state["_hash"] = digest
        if snap_digest and snap_digest != state["_snap_hash"]:
            api.upload_file(path_or_fileobj=str(snap), path_in_repo=SNAPSHOT, repo_id=config.STATE_REPO,
                            repo_type="dataset", commit_message=f"risk map {stamp}")
            state["_snap_hash"] = snap_digest
        state["last_backup"], state["last_error"] = datetime.now().isoformat(timespec="seconds"), None
        return True
    except Exception as err:
        state["last_error"] = f"backup failed: {type(err).__name__}: {str(err)[:200]}"
        print(f"[backup] {state['last_error']}", flush=True)
        return False
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


async def backup_loop() -> None:
    try:
        while True:
            await asyncio.sleep(config.STATE_BACKUP_MIN * 60)
            await asyncio.to_thread(backup)
    except asyncio.CancelledError:
        await asyncio.to_thread(backup)            # last copy when the server stops
        raise


def summary() -> str:
    if not enabled():
        return "off (the database lives only on this machine's disk)"
    last = state["last_backup"] or "none yet this run"
    err = f"; PROBLEM: {state['last_error']}" if state["last_error"] else ""
    return (f"every {config.STATE_BACKUP_MIN:g} min to private dataset {config.STATE_REPO} "
            f"(last copy: {last}; start-up: {state['restored'] or '-'}){err}")
