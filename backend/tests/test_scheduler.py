"""Tests for automatic scoring, with scoring and drafting mocked (no network)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.jobs import scheduler

SNAP = {"summary": {"HIGH": 1, "MEDIUM": 2, "LOW": 5}, "villages": []}


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(scheduler, "state", {**scheduler.state, "runs": 0, "last_error": None,
                                             "last_alerts_created": [], "running_now": False})


def test_cycle_scores_then_drafts(monkeypatch):
    monkeypatch.setattr(scheduler, "score_now", lambda: SNAP)
    monkeypatch.setattr(scheduler, "generate_for_snapshot", lambda s: [{"id": 7}])
    result = asyncio.run(scheduler.run_once_tracked())
    assert result == {"summary": SNAP["summary"], "alerts_created": [7]}
    assert scheduler.state["runs"] == 1 and scheduler.state["last_error"] is None
    assert scheduler.state["last_summary"]["HIGH"] == 1


def test_failed_cycle_is_recorded_not_raised(monkeypatch):
    def down():
        raise RuntimeError("Open-Meteo forecast unavailable")

    monkeypatch.setattr(scheduler, "score_now", down)
    result = asyncio.run(scheduler.run_once_tracked())
    assert "unavailable" in result["error"]
    assert "unavailable" in scheduler.state["last_error"]
    assert scheduler.state["running_now"] is False


def test_loop_keeps_running_after_a_failure(monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first run fails")
        return SNAP

    monkeypatch.setattr(scheduler, "score_now", flaky)
    monkeypatch.setattr(scheduler, "generate_for_snapshot", lambda s: [])
    monkeypatch.setattr(config, "SCHEDULER_FIRST_RUN_DELAY_S", 0)
    monkeypatch.setattr(config, "SCORING_INTERVAL_MIN", 0.0005)   # 0.03 s between runs

    async def run_briefly():
        try:
            await asyncio.wait_for(scheduler.scheduler_loop(), timeout=0.3)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run_briefly())
    assert len(calls) >= 2                       # it ran again after the failure
    assert scheduler.state["last_error"] is None  # and the later run succeeded


def test_status_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(config, "ALERTS_DB", tmp_path / "alerts.db")
    from backend.app.main import app
    from backend.tests.conftest import sign_in
    with TestClient(app) as c:
        assert c.get("/system/scheduler").status_code == 401      # signed out
        sign_in(c)
        body = c.get("/system/scheduler").json()
    assert body["runs"] == 0 and body["running_now"] is False
