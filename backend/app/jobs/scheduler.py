"""
Automatic scoring: while the server runs, score every rain-grid square in Karnataka on a
fixed interval and draft alerts for taluks that turn HIGH.

How it runs
  * Started by main.py when the server starts (if SCHEDULER_ENABLED), stopped when it stops.
  * First run shortly after startup, then every SCORING_INTERVAL_MIN minutes.
  * The work itself (HTTP calls, SQLite) is ordinary blocking code, so each cycle runs
    in a worker thread (asyncio.to_thread) and the API stays responsive meanwhile.
  * A failed cycle (e.g. forecast API down) is recorded and retried at the next interval;
    it never stops the loop or the server.

Limits worth knowing
  * It only runs while the server process runs. On a free host that sleeps when idle
    (Render free tier), it pauses too.
  * Run the server with ONE worker; several workers would each run their own scheduler.
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config
from ..services.alerts import generate_for_snapshot
from .score_grid import score_now

state = {
    "enabled": False,
    "interval_minutes": None,
    "runs": 0,
    "running_now": False,
    "last_run_at": None,
    "last_duration_s": None,
    "last_summary": None,        # {"HIGH": n, "MEDIUM": n, "LOW": n}
    "last_alerts_created": [],   # alert ids
    "last_error": None,
    "next_run_at": None,
}


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def run_cycle() -> dict:
    """One full pass: score the whole state, then draft alerts for new HIGH taluks."""
    snapshot = score_now()
    created = generate_for_snapshot(snapshot)
    return {"summary": snapshot["summary"], "alerts_created": [a["id"] for a in created]}


async def run_once_tracked() -> dict:
    """Run a cycle in a worker thread and record the outcome in `state`."""
    started = _now()
    state["running_now"] = True
    try:
        result = await asyncio.to_thread(run_cycle)
        state.update(last_summary=result["summary"], last_alerts_created=result["alerts_created"],
                     last_error=None)
        s = result["summary"]
        print(f"[scheduler] {started:%H:%M} scored rain-grid squares: HIGH {s['HIGH']}  MEDIUM {s['MEDIUM']}  "
              f"LOW {s['LOW']}  | alerts drafted: {len(result['alerts_created'])}", flush=True)
        return result
    except Exception as err:
        state["last_error"] = f"{type(err).__name__}: {err}"[:500]
        print(f"[scheduler] {started:%H:%M} cycle failed: {state['last_error']}", flush=True)
        return {"error": state["last_error"]}
    finally:
        state["running_now"] = False
        state["runs"] += 1
        state["last_run_at"] = started.isoformat(timespec="seconds")
        state["last_duration_s"] = round((_now() - started).total_seconds(), 1)


async def scheduler_loop() -> None:
    interval = config.SCORING_INTERVAL_MIN
    state.update(enabled=True, interval_minutes=interval)
    first = _now() + timedelta(seconds=config.SCHEDULER_FIRST_RUN_DELAY_S)
    state["next_run_at"] = first.isoformat(timespec="seconds")
    print(f"[scheduler] started: first run at {first:%H:%M:%S}, then every {interval:g} min", flush=True)
    await asyncio.sleep(config.SCHEDULER_FIRST_RUN_DELAY_S)
    while True:
        await run_once_tracked()
        nxt = _now() + timedelta(minutes=interval)
        state["next_run_at"] = nxt.isoformat(timespec="seconds")
        await asyncio.sleep(interval * 60)
