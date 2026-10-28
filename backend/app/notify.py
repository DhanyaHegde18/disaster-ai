"""
Push alerts to staff phones, so an emergency is noticed even when nobody has the dashboard open.

Uses ntfy (https://ntfy.sh): free, open source, no account needed. Each staff member installs
the ntfy app and subscribes to THEIR topic, which the dashboard shows them after sign-in:

  Gram Panchayat, one taluk   <NTFY_TOPIC_GP>-<taluk>        e.g. gp-3f9a...-dakshina-kannada-belthangady
  NGO, one district           <NTFY_TOPIC_NGO>-<district>    e.g. ngo-7c1d...-udupi
  state level (no area set)   <NTFY_TOPIC_GP> / <NTFY_TOPIC_NGO>   (gets everything in Karnataka)

So a rescue request in Belthangady rings Belthangady's GP phones and Dakshina Kannada's NGOs,
not every phone in the state. The secret prefixes in .env keep topics unguessable.
Priority 5 ("urgent") gives long vibration bursts and a pop-over on Android.

What gets sent (see also jobs/escalation.py):
  rescue request              -> GP + NGO, urgent, repeated until a GP marks it handled
  alert waiting for review    -> GP, high, repeated (urgent) until approved or rejected
  relief centre opened        -> GP + NGO, normal, once
  relief centre (nearly) full -> GP + NGO, high, once

Every send is recorded in `staff_notifications`, so the escalation check knows what was
already sent and when. A failed send is logged and never breaks the request that caused it.
"""
import re

import requests

from . import areas, config, database

URGENT, HIGH = 5, 4
NEARLY_FULL = 0.9        # a relief centre at 90% of its places counts as nearly full


LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "testserver")


def request_base(request) -> tuple[str, str]:
    """(scheme, host) the visitor used, as seen through a tunnel (cloudflared / Tailscale add X-Forwarded-*)."""
    h = request.headers
    scheme = (h.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (h.get("x-forwarded-host") or h.get("host") or "").split(",")[0].strip()
    return scheme, host


def learn_public_url(request) -> None:
    """Remember the address staff reach the dashboard on, for the links in phone notifications.
    Only called for signed-in staff, so a stranger can't point notification links elsewhere.
    An https address (tunnel / Tailscale) is preferred over a plain Wi-Fi one."""
    scheme, host = request_base(request)
    if not host or host.split(":")[0] in LOCAL_HOSTS:
        return
    url = f"{scheme}://{host}"
    current = learned_public_url()
    if url == current or (current and current.startswith("https://") and scheme != "https"):
        return
    with database.connect() as c:
        c.execute("INSERT INTO app_meta (key, value) VALUES ('public_url', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (url,))


def learned_public_url() -> str | None:
    with database.connect() as c:
        r = c.execute("SELECT value FROM app_meta WHERE key = 'public_url'").fetchone()
    return r["value"] if r else None


def public_url() -> str:
    """PUBLIC_URL from .env if set, else the address the dashboard was last opened on, else localhost."""
    return config.PUBLIC_URL or learned_public_url() or "http://127.0.0.1:8000"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _base(role: str) -> str:
    return {"gp": config.NTFY_TOPIC_GP, "admin": config.NTFY_TOPIC_GP, "ngo": config.NTFY_TOPIC_NGO}.get(role, "")


def topics_for(roles: tuple[str, ...], taluk_id: str | None = None) -> list[str]:
    """Topics to send to: the state-level topic of each role, plus the taluk's (GP) and
    district's (NGO) own topics when the event has a place."""
    t = areas.get().taluk(taluk_id) if taluk_id else None
    out = []
    for role in roles:
        base = _base(role)
        if not base:
            continue
        out.append(base)
        if t:
            out.append(f"{base}-{_slug(t['taluk_id'])}" if role == "gp" else f"{base}-{_slug(t['district'])}")
    return out


def topic_for_user(user: dict) -> str | None:
    """The one topic this staff member should subscribe to in the ntfy app."""
    base = _base(user.get("role", ""))
    if not base:
        return None
    if user["role"] == "gp" and user.get("taluk_id"):
        return f"{base}-{_slug(user['taluk_id'])}"
    if user["role"] == "ngo" and user.get("district"):
        return f"{base}-{_slug(user['district'])}"
    return base


def send_code(topic: str, code: str, who: str) -> bool:
    """A dashboard sign-in code, to one staff member's own topic. True if ntfy accepted it."""
    try:
        r = requests.post(f"{config.NTFY_SERVER}/{topic}", timeout=10,
                          data=f"Dashboard sign-in code for {who}: {code} (valid {config.OTP_TTL_MIN} min). "
                               f"Don't share it.".encode("utf-8"),
                          headers={"Title": "Sign-in code", "Priority": "4", "Tags": "key"})
        return r.status_code < 300
    except requests.RequestException:
        return False


def push(roles: tuple[str, ...], title: str, message: str, priority: int = HIGH,
         tags: str = "warning", path: str = "/", taluk_id: str | None = None) -> int:
    """Send to every configured topic for `roles` (and the place). Returns how many accepted it."""
    ok = 0
    for topic in topics_for(roles, taluk_id):
        try:
            r = requests.post(f"{config.NTFY_SERVER}/{topic}", data=message.encode("utf-8"), timeout=10,
                              headers={"Title": title, "Priority": str(priority),
                                       "Tags": tags, "Click": f"{public_url()}{path}"})
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


# ---------- what gets sent ----------

def rescue_key(report: dict) -> str:
    return f"rescue:{report['phone']}:{report['reported_at']}"


def notify_rescue(report: dict, repeat: int = 0) -> None:
    v = areas.get().village(report["village_id"]) or {"name": report["village_id"], "taluk": "", "taluk_id": None}
    people = sum(report[k] for k in ("at_shelter", "with_relatives", "at_home", "unknown"))
    again = f" (reminder {repeat}: still not handled)" if repeat else ""
    late = (f" Written at {report['queued_at'][11:16]} with no network, so it may be urgent already."
            if report.get("queued_at") else "")
    push(("gp", "ngo"), f"RESCUE requested: {v['name']}, {v['taluk']}".rstrip(", "),
         f"A family in {v['name']} ({people} people, {report['unknown']} unknown) asked for urgent rescue{again}.{late} "
         f"Open the dashboard, call them and mark it handled.",
         priority=URGENT, tags="rotating_light,sos", taluk_id=v["taluk_id"])
    record(rescue_key(report))


def notify_shelter_change(before: dict, after: dict) -> None:
    """Tell staff when a relief centre opens, or fills up (no reminders: one message each)."""
    where = (areas.get().taluk(after.get("taluk_id") or "") or {}).get("name", "")
    suffix = f": {where}" if where else ""
    if after["is_open"] and not before["is_open"]:
        push(("gp", "ngo"), f"Relief centre opened{suffix}",
             f"{after['name']} is now open ({after['capacity']} places). Send families there.",
             priority=3, tags="house", taluk_id=after.get("taluk_id"))
    # One message when it passes 90% and another when it is completely full.
    crossed = [word for word, level in (("FULL", after["capacity"]), ("nearly full", after["capacity"] * NEARLY_FULL))
               if after["occupancy"] >= level > before["occupancy"]]
    if after["is_open"] and crossed:
        push(("gp", "ngo"), f"Relief centre {crossed[0]}{suffix}",
             f"{after['name']}: {after['occupancy']} people, {after['capacity']} places. "
             f"Open another centre or arrange more space.", priority=HIGH, tags="house,warning",
             taluk_id=after.get("taluk_id"))


def alert_key(alert: dict) -> str:
    return f"alert:{alert['id']}"


def notify_pending_alert(alert: dict, repeat: int = 0) -> None:
    if alert.get("simulated"):
        return   # test drafts are made by someone at the screen
    again = f" Reminder {repeat}: villagers have NOT been warned yet." if repeat else ""
    push(("gp",), f"Alert waiting: {alert['taluk_name']} ({alert['level']})",
         f"A warning for {alert['taluk_name']} taluk is waiting for your approval.{again}",
         priority=URGENT if repeat else HIGH, tags="warning", taluk_id=alert["taluk_id"])
    record(alert_key(alert))
