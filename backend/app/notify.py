"""
Push alerts to staff phones, so an emergency is noticed even when nobody has the dashboard open.

Uses ntfy (https://ntfy.sh): free, open source, no account needed. Each staff member installs
the ntfy app and subscribes to their role's topic (NTFY_TOPIC_GP / NTFY_TOPIC_NGO in .env).
Priority 5 ("urgent") gives long vibration bursts and a pop-over on Android.

What gets sent (see also jobs/escalation.py):
  rescue request           -> Gram Panchayat + NGOs, urgent, repeated until a GP marks it handled
  alert waiting for review -> Gram Panchayat, high, repeated (urgent) until approved or rejected

Every send is recorded in `staff_notifications`, so the escalation check knows what was
already sent and when. A failed send is logged and never breaks the request that caused it.
"""
import requests

from . import config, database

URGENT, HIGH = 5, 4


def topics_for(roles: tuple[str, ...]) -> list[str]:
    topics = {"gp": config.NTFY_TOPIC_GP, "ngo": config.NTFY_TOPIC_NGO}
    return [topics[r] for r in roles if topics.get(r)]


def push(roles: tuple[str, ...], title: str, message: str, priority: int = HIGH,
         tags: str = "warning", path: str = "/") -> int:
    """Send to every configured topic for `roles`. Returns how many topics accepted it."""
    ok = 0
    for topic in topics_for(roles):
        try:
            r = requests.post(f"{config.NTFY_SERVER}/{topic}", data=message.encode("utf-8"), timeout=10,
                              headers={"Title": title, "Priority": str(priority),
                                       "Tags": tags, "Click": f"{config.PUBLIC_URL}{path}"})
            if r.status_code < 300:
                ok += 1
            else:
                print(f"[notify] ntfy refused ({r.status_code}): {r.text[:120]}", flush=True)
        except requests.RequestException as err:
            print(f"[notify] could not reach ntfy: {type(err).__name__}", flush=True)
    return ok


def record(key: str) -> None:
    """Remember that `key` was alerted now (first time, or one more repeat)."""
    now = database.now()
    with database.connect() as c:
        c.execute("""INSERT INTO staff_notifications (key, first_sent_at, last_sent_at, times)
                     VALUES (?, ?, ?, 1)
                     ON CONFLICT(key) DO UPDATE SET last_sent_at = excluded.last_sent_at, times = times + 1""",
                  (key, now, now))


def sent_info(key: str) -> dict | None:
    with database.connect() as c:
        r = c.execute("SELECT * FROM staff_notifications WHERE key = ?", (key,)).fetchone()
        return dict(r) if r else None


# ---------- the two kinds of alert ----------

def rescue_key(report: dict) -> str:
    return f"rescue:{report['phone']}:{report['reported_at']}"


def notify_rescue(report: dict, village_name: str, repeat: int = 0) -> None:
    people = sum(report[k] for k in ("at_shelter", "with_relatives", "at_home", "unknown"))
    again = f" (reminder {repeat}: still not handled)" if repeat else ""
    push(("gp", "ngo"), f"RESCUE requested: {village_name}",
         f"A family in {village_name} ({people} people, {report['unknown']} unknown) asked for urgent rescue{again}. "
         f"Open the dashboard, call them and mark it handled.",
         priority=URGENT, tags="rotating_light,sos")
    record(rescue_key(report))


def alert_key(alert: dict) -> str:
    return f"alert:{alert['id']}"


def notify_pending_alert(alert: dict, repeat: int = 0) -> None:
    if alert.get("simulated"):
        return   # test drafts are made by someone at the screen
    again = f" Reminder {repeat}: villagers have NOT been warned yet." if repeat else ""
    push(("gp",), f"Alert waiting: {alert['village_name']} ({alert['level']})",
         f"A warning for {alert['village_name']} is waiting for your approval.{again}",
         priority=URGENT if repeat else HIGH, tags="warning")
    record(alert_key(alert))
