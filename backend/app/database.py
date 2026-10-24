"""
Storage in SQLite (a single file, no server to run): alerts, staff and villager sign-in,
and evacuation reports.

An alert moves through these states:
    pending  -> approved   (Gram Panchayat approved it; the villager app may show it)
    pending  -> rejected   (not sent; reason kept)
Only pending alerts can be edited. Every change is timestamped.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    village_id     TEXT NOT NULL,
    village_name   TEXT NOT NULL,
    level          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    message_kn     TEXT NOT NULL,
    message_en     TEXT NOT NULL,
    source         TEXT NOT NULL,          -- 'gemini' or 'template'
    source_note    TEXT,                   -- model name, or why the template was used
    simulated      INTEGER NOT NULL DEFAULT 0,
    edited         INTEGER NOT NULL DEFAULT 0,
    risk_json      TEXT NOT NULL,          -- the risk result the alert was drafted from
    created_at     TEXT NOT NULL,
    reviewed_by    TEXT,
    reviewed_at    TEXT,
    review_note    TEXT
);

-- Staff allowed to sign in to the dashboard, added by whoever runs the server
-- (python -m backend.app.jobs.officials add ...). role: 'gp' (Gram Panchayat) or 'ngo'.
CREATE TABLE IF NOT EXISTS officials (
    phone       TEXT PRIMARY KEY,      -- +91XXXXXXXXXX
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'gp'
);

-- Villagers who signed in to report their family's status (they register themselves).
CREATE TABLE IF NOT EXISTS villagers (
    phone       TEXT PRIMARY KEY,
    village_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Each family's latest evacuation status (one row per phone; a new report replaces the old one).
CREATE TABLE IF NOT EXISTS evacuation_reports (
    phone           TEXT PRIMARY KEY,
    village_id      TEXT NOT NULL,
    at_shelter      INTEGER NOT NULL DEFAULT 0,   -- at a relief centre (ಕಾಳಜಿ ಕೇಂದ್ರ)
    with_relatives  INTEGER NOT NULL DEFAULT 0,   -- relatives / another village
    at_home         INTEGER NOT NULL DEFAULT 0,   -- stayed at home
    unknown         INTEGER NOT NULL DEFAULT 0,   -- whereabouts unknown
    needs           TEXT NOT NULL DEFAULT '[]',   -- JSON list, e.g. ["rescue", "water"]
    reported_at     TEXT NOT NULL,
    handled_by      TEXT,                         -- GP official who dealt with a rescue request
    handled_at      TEXT
);

-- Phone alerts already sent to staff, so reminders go out on schedule and not twice.
CREATE TABLE IF NOT EXISTS staff_notifications (
    key            TEXT PRIMARY KEY,              -- e.g. 'alert:12' or 'rescue:+91...:<reported_at>'
    first_sent_at  TEXT NOT NULL,
    last_sent_at   TEXT NOT NULL,
    times          INTEGER NOT NULL DEFAULT 1
);
"""

# Sign-in codes and sessions are short-lived, so if their layout changes we can simply
# recreate them (everyone just signs in again). They're kept separate for that reason.
TRANSIENT = {
    "otp_codes": """
CREATE TABLE IF NOT EXISTS otp_codes (
    phone       TEXT NOT NULL,
    purpose     TEXT NOT NULL,         -- 'staff' or 'villager'
    code_hash   TEXT NOT NULL,         -- 'twilio' when Twilio Verify holds the code
    sent_at     TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (phone, purpose)
);""",
    "sessions": """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    kind        TEXT NOT NULL,         -- 'staff' or 'villager'
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);""",
}
TRANSIENT_REQUIRED = {"otp_codes": "purpose", "sessions": "kind"}


def now() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds")


@contextmanager
def connect():
    config.ALERTS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.ALERTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(c, table: str) -> set[str]:
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    """Create tables, and upgrade a database made by an earlier version of this code."""
    with connect() as c:
        c.executescript(SCHEMA)
        if "role" not in _columns(c, "officials"):          # added when NGOs got their own role
            c.execute("ALTER TABLE officials ADD COLUMN role TEXT NOT NULL DEFAULT 'gp'")
        report_cols = _columns(c, "evacuation_reports")
        for col in ("handled_by", "handled_at"):              # added with rescue follow-up
            if col not in report_cols:
                c.execute(f"ALTER TABLE evacuation_reports ADD COLUMN {col} TEXT")
        for table, ddl in TRANSIENT.items():
            cols = _columns(c, table)
            if cols and TRANSIENT_REQUIRED[table] not in cols:
                c.execute(f"DROP TABLE {table}")              # old layout: recreate
            c.executescript(ddl)


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["risk"] = json.loads(d.pop("risk_json"))
    d["simulated"] = bool(d["simulated"])
    d["edited"] = bool(d["edited"])
    return d


def create_alert(risk: dict, draft: dict, simulated: bool = False) -> dict:
    with connect() as c:
        cur = c.execute(
            """INSERT INTO alerts (village_id, village_name, level, message_kn, message_en,
                                   source, source_note, simulated, risk_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (risk["village_id"], risk["name"], risk["level"], draft["kn"], draft["en"],
             draft["source"], draft.get("note"), int(simulated),
             json.dumps(risk, ensure_ascii=False), now()),
        )
        return get_alert(cur.lastrowid, c)


def get_alert(alert_id: int, conn=None) -> dict | None:
    if conn is not None:
        return _row(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
    with connect() as c:
        return _row(c.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())


def list_alerts(status: str | None = None, limit: int = 100) -> list[dict]:
    with connect() as c:
        if status:
            rows = c.execute("SELECT * FROM alerts WHERE status = ? ORDER BY id DESC LIMIT ?",
                             (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]


def open_alert_today(village_id: str) -> dict | None:
    """A real (non-simulated) pending/approved alert for this village created today, if any.
    Used so the scheduled job doesn't draft a new alert every few hours."""
    today = now()[:10]
    with connect() as c:
        r = c.execute(
            """SELECT * FROM alerts WHERE village_id = ? AND simulated = 0
               AND status IN ('pending', 'approved') AND substr(created_at, 1, 10) = ?
               ORDER BY id DESC LIMIT 1""",
            (village_id, today),
        ).fetchone()
        return _row(r)


def list_public_alerts(village_id: str, include_simulated: bool = False, days: int = 7) -> list[dict]:
    """Alerts villagers may see: APPROVED only, for one village, approved in the last `days` days.
    Simulated (test) alerts are left out unless include_simulated is set (demo mode)."""
    since = (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)).isoformat(timespec="seconds")
    sql = ("SELECT * FROM alerts WHERE village_id = ? AND status = 'approved' AND reviewed_at >= ?"
           + ("" if include_simulated else " AND simulated = 0")
           + " ORDER BY reviewed_at DESC")
    with connect() as c:
        return [_row(r) for r in c.execute(sql, (village_id, since)).fetchall()]


def update_text(alert_id: int, message_kn: str | None, message_en: str | None) -> dict:
    with connect() as c:
        a = get_alert(alert_id, c)
        if a is None:
            raise KeyError(alert_id)
        if a["status"] != "pending":
            raise ValueError(f"Only pending alerts can be edited (this one is {a['status']})")
        c.execute("UPDATE alerts SET message_kn = ?, message_en = ?, edited = 1 WHERE id = ?",
                  (message_kn or a["message_kn"], message_en or a["message_en"], alert_id))
        return get_alert(alert_id, c)


def review(alert_id: int, decision: str, reviewed_by: str, note: str | None) -> dict:
    assert decision in ("approved", "rejected")
    with connect() as c:
        a = get_alert(alert_id, c)
        if a is None:
            raise KeyError(alert_id)
        if a["status"] != "pending":
            raise ValueError(f"Alert {alert_id} is already {a['status']}")
        c.execute("UPDATE alerts SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? "
                  "WHERE id = ?", (decision, reviewed_by, now(), note, alert_id))
        return get_alert(alert_id, c)
