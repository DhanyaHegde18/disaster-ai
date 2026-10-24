"""
Reminders until someone acts. Runs every minute while the server runs (if ntfy topics are set).

  Open rescue request (not marked handled)   -> remind GP + NGO phones every ESCALATE_AFTER_MIN
  Real alert still pending (not reviewed)     -> remind GP phones every ESCALATE_AFTER_MIN (urgent)
Each item is alerted at most ESCALATE_MAX_TIMES times, then the reminders stop.
"""
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config, database, notify
from ..routers.relief import REPORT_DAYS


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _due(key: str, now: datetime) -> tuple[bool, int]:
    """(should we alert now?, how many times already)."""
    info = notify.sent_info(key)
    if info is None:
        return True, 0                       # never alerted (e.g. topics were added later)
    if info["times"] >= config.ESCALATE_MAX_TIMES:
        return False, info["times"]
    waited = now - datetime.fromisoformat(info["last_sent_at"])
    return waited >= timedelta(minutes=config.ESCALATE_AFTER_MIN), info["times"]


def check_once(now: datetime | None = None) -> dict:
    now = now or _now()
    sent = {"alerts": 0, "rescues": 0}
    if not notify.topics_for(("gp", "ngo")):
        return sent                          # no phones configured: nothing to do
    names = {v["village_id"]: v["name"] for v in config.rule_config()["villages"]}

    for alert in database.list_alerts("pending"):
        if alert["simulated"]:
            continue
        due, times = _due(notify.alert_key(alert), now)
        if due:
            notify.notify_pending_alert(alert, repeat=times)
            sent["alerts"] += 1

    since = (now - timedelta(days=REPORT_DAYS)).isoformat(timespec="seconds")
    with database.connect() as c:
        rows = c.execute("SELECT * FROM evacuation_reports WHERE handled_at IS NULL AND reported_at >= ?",
                         (since,)).fetchall()
    for r in rows:
        report = dict(r)
        if "rescue" not in json.loads(report["needs"]):
            continue
        due, times = _due(notify.rescue_key(report), now)
        if due:
            notify.notify_rescue(report, names.get(report["village_id"], report["village_id"]), repeat=times)
            sent["rescues"] += 1
    return sent


async def escalation_loop() -> None:
    print(f"[escalation] phone reminders on: every {config.ESCALATE_AFTER_MIN:g} min until handled", flush=True)
    while True:
        try:
            result = await asyncio.to_thread(check_once)
            if result["alerts"] or result["rescues"]:
                print(f"[escalation] reminders sent: {result}", flush=True)
        except Exception as err:   # never let a bad check stop the loop
            print(f"[escalation] check failed: {type(err).__name__}: {err}", flush=True)
        await asyncio.sleep(config.ESCALATION_CHECK_S)
