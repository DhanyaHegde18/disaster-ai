"""
Sign-in with phone number + one-time code (OTP), then a session cookie.

Two kinds of people sign in:
  staff     Gram Panchayat officials (role 'gp') and NGO workers (role 'ngo').
            Only numbers in the `officials` table, added by whoever runs the server
            (python -m backend.app.jobs.officials add ...). No self-registration: staff see
            villagers' evacuation data, and GP officials approve alerts.
  villager  Anyone with an Indian mobile number, only to report their family's evacuation
            status. Seeing warnings never needs a sign-in.

Codes
  6 digits, valid OTP_TTL_MIN minutes, OTP_MAX_ATTEMPTS wrong tries, one request per
  OTP_RESEND_S seconds, usable once. Only a hash is stored. Sent by the SMS provider in
  SMS_PROVIDER (see sms.py); in demo mode the code is shown on screen.

Sessions
  A random token in an httpOnly, SameSite=Strict cookie (separate cookies for staff and
  villagers). Only a hash is stored server-side.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from . import areas, config, database, sms

STAFF, VILLAGER = "staff", "villager"
COOKIES = {STAFF: "gp_session", VILLAGER: "v_session"}
COOKIE = COOKIES[STAFF]          # kept for older imports
ROLES = ("gp", "ngo", "admin")    # admin: whole state, everything a GP can do, and gives others access


class AuthError(Exception):
    """A sign-in problem to show to the user, with an HTTP status."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_phone(raw: str) -> str:
    """Accept 9876543210, 09876543210, +91 98765 43210 ... and return +919876543210."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise AuthError("Enter a 10-digit Indian mobile number.")
    return "+91" + digits


def mask(phone: str) -> str:
    return phone[:3] + "•" * 6 + phone[-4:]


# ---------- staff accounts ----------

def add_official(phone: str, name: str, role: str = "gp", taluk_id: str | None = None,
                 district: str | None = None) -> dict:
    """Gram Panchayat officials work in one taluk (they see and approve only that taluk).
    NGO staff may be limited to a district. Leaving both empty means all of Karnataka."""
    phone, role = normalize_phone(phone), role.lower()
    if role not in ROLES:
        raise AuthError(f"Role must be one of: {', '.join(ROLES)}")
    if role == "admin":
        taluk_id = district = None                       # the admin covers all of Karnataka
    a = areas.get()
    if taluk_id:
        t = a.taluk(taluk_id)
        if not t:
            raise AuthError(f"Unknown taluk '{taluk_id}'.")
        district = t["district"]
    elif district:
        district = a.find_district(district)
        if not district:
            raise AuthError("Unknown district.")
    with database.connect() as c:
        c.execute("INSERT INTO officials (phone, name, created_at, role, district, taluk_id) VALUES (?, ?, ?, ?, ?, ?) "
                  "ON CONFLICT(phone) DO UPDATE SET name = excluded.name, role = excluded.role, "
                  "district = excluded.district, taluk_id = excluded.taluk_id",
                  (phone, name.strip(), database.now(), role, district, taluk_id))
    return get_official(phone)


def _with_scope(o: dict) -> dict:
    """Add a readable area name: 'Belthangady taluk, Dakshina Kannada', 'Udupi district' or 'All of Karnataka'."""
    t = areas.get().taluk(o["taluk_id"]) if o.get("taluk_id") else None
    o["taluk_name"] = t["name"] if t else None
    o["area"] = (f"{t['name']} taluk, {t['district']}" if t
                 else f"{o['district']} district" if o.get("district") else "All of Karnataka")
    return o


def scope_taluks(user: dict) -> set[str] | None:
    """Taluks this staff member may see; None means all of Karnataka."""
    if user.get("taluk_id"):
        return {user["taluk_id"]}
    if user.get("district"):
        return set(areas.get().taluks_in_district(user["district"]))
    return None


def in_scope(user: dict, taluk_id: str | None) -> bool:
    allowed = scope_taluks(user)
    return allowed is None or taluk_id in allowed


def remove_official(phone: str) -> bool:
    phone = normalize_phone(phone)
    with database.connect() as c:
        removed = c.execute("DELETE FROM officials WHERE phone = ?", (phone,)).rowcount
        c.execute("DELETE FROM sessions WHERE phone = ? AND kind = ?", (phone, STAFF))  # signed out everywhere
    return bool(removed)


GUEST_PREFIX = "Guest ····"


def is_guest(official: dict) -> bool:
    """Signed up by themselves under OPEN_SIGNIN (their codes are shown on screen, never sent anywhere)."""
    return (official.get("name") or "").startswith(GUEST_PREFIX)


def seed_officials(text: str) -> tuple[list[dict], list[str]]:
    """Add/update staff from the OFFICIALS setting (for servers without a shell):
    one per line or ';' -> phone, name, role, district, taluk. Returns (added, problems)."""
    added, problems = [], []
    for raw in re.split(r"[;\n]", text or ""):
        parts = [x.strip() for x in raw.split(",")]
        if not parts or not parts[0]:
            continue
        phone, name = parts[0], (parts[1] if len(parts) > 1 and parts[1] else "Staff")
        role = (parts[2] if len(parts) > 2 and parts[2] else "gp").lower()
        district = parts[3] if len(parts) > 3 and parts[3] else None
        taluk = parts[4] if len(parts) > 4 and parts[4] else None
        try:
            taluk_id = None
            if taluk:
                found = areas.get().find_taluk(taluk, district)
                if len(found) != 1:
                    raise AuthError(f"taluk '{taluk}' " + ("not found" if not found else "is ambiguous; add the district"))
                taluk_id = found[0]["taluk_id"]
            added.append(add_official(phone, name, role, taluk_id=taluk_id, district=district))
        except AuthError as err:
            problems.append(f"line '{name}': {err}")
    return added, problems


def list_officials() -> list[dict]:
    with database.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT phone, name, role, district, taluk_id, created_at "
                                           "FROM officials ORDER BY role, district, name")]
    return [_with_scope(o) for o in rows]


def get_official(phone: str) -> dict | None:
    with database.connect() as c:
        r = c.execute("SELECT phone, name, role, district, taluk_id FROM officials WHERE phone = ?", (phone,)).fetchone()
    return _with_scope(dict(r)) if r else None


# ---------- codes ----------

def request_code(raw_phone: str, purpose: str = STAFF) -> dict:
    phone = normalize_phone(raw_phone)
    official = get_official(phone) if purpose == STAFF else None
    if purpose == STAFF and not official:
        if config.OPEN_SIGNIN in ("viewer", "gp"):            # demo: anyone may look around
            official = add_official(phone, f"{GUEST_PREFIX}{phone[-4:]}", "ngo" if config.OPEN_SIGNIN == "viewer" else "gp",
                                    taluk_id=config.OPEN_SIGNIN_TALUK if config.OPEN_SIGNIN == "gp" else None)
        else:
            raise AuthError("This number is not registered for the dashboard. "
                            "Ask the person who runs the system to add it.", 403)
    guest = bool(official and is_guest(official))
    now = _now()
    with database.connect() as c:
        row = c.execute("SELECT sent_at FROM otp_codes WHERE phone = ? AND purpose = ?", (phone, purpose)).fetchone()
    if row:
        wait = config.OTP_RESEND_S - (now - datetime.fromisoformat(row["sent_at"])).total_seconds()
        if wait > 0:
            raise AuthError(f"Please wait {int(wait) + 1} seconds before asking for a new code.", 429)

    provider, code = ("demo" if guest else config.SMS_PROVIDER), None      # guests: code on screen
    try:
        if provider == "twilio":
            sms.twilio_start(phone)                 # Twilio makes and remembers the code
            code_hash = "twilio"
        elif provider in ("fast2sms", "demo", "ntfy"):
            code = f"{secrets.randbelow(10**6):06d}"
            code_hash = _hash(f"{phone}|{purpose}|{code}")
            if provider == "fast2sms":
                sms.fast2sms_send(phone, code)
            elif provider == "ntfy" and purpose == STAFF:
                from . import notify                # staff code to the alarm topic their phone follows
                topic = notify.topic_for_user(get_official(phone))
                if not topic:
                    raise AuthError("Sign-in codes go by ntfy, but no ntfy topic is set on the server "
                                    "(NTFY_TOPIC_GP / NTFY_TOPIC_NGO).", 500)
                why = notify.send_code(topic, code, mask(phone))
                if why:
                    raise sms.SMSError(why)
            elif provider == "ntfy":
                provider = "screen"                 # villagers have no ntfy topic: shown on screen
        else:
            raise AuthError(f"Unknown SMS_PROVIDER '{provider}'. Use demo, twilio, fast2sms or ntfy.", 500)
    except sms.SMSError as err:
        raise AuthError(f"Could not send the code: {err}", 502)

    with database.connect() as c:
        c.execute("INSERT OR REPLACE INTO otp_codes (phone, purpose, code_hash, sent_at, expires_at, attempts) "
                  "VALUES (?, ?, ?, ?, ?, 0)",
                  (phone, purpose, code_hash, now.isoformat(timespec="seconds"),
                   (now + timedelta(minutes=config.OTP_TTL_MIN)).isoformat(timespec="seconds")))
    result = {"phone": mask(phone), "expires_in_min": config.OTP_TTL_MIN, "sent_by": provider}
    if provider in ("demo", "screen"):
        result["demo_code"] = code              # no SMS: the screen shows the code
    return result


def _code_matches(row, phone: str, purpose: str, code: str) -> bool:
    if row["code_hash"] == "twilio":
        try:
            return sms.twilio_check(phone, code)
        except sms.SMSError as err:
            raise AuthError(f"Could not check the code: {err}", 502)
    return secrets.compare_digest(row["code_hash"], _hash(f"{phone}|{purpose}|{code}"))


def verify_code(raw_phone: str, code: str, purpose: str = STAFF, village_id: str | None = None) -> tuple[str, dict]:
    """Check the code; on success return (session token, user)."""
    phone = normalize_phone(raw_phone)
    code = (code or "").strip()
    if purpose == VILLAGER and not areas.get().village(village_id or ""):
        raise AuthError("Choose your village first.", 422)
    now = _now()
    with database.connect() as c:
        row = c.execute("SELECT * FROM otp_codes WHERE phone = ? AND purpose = ?", (phone, purpose)).fetchone()
    if not row or now > datetime.fromisoformat(row["expires_at"]):
        raise AuthError("This code has expired. Ask for a new one.", 401)
    if row["attempts"] >= config.OTP_MAX_ATTEMPTS:
        raise AuthError("Too many wrong tries. Ask for a new code.", 429)

    if not _code_matches(row, phone, purpose, code):
        with database.connect() as c:
            c.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE phone = ? AND purpose = ?", (phone, purpose))
        left = config.OTP_MAX_ATTEMPTS - row["attempts"] - 1
        raise AuthError(f"Wrong code. {left} tr{'y' if left == 1 else 'ies'} left."
                        if left else "Wrong code. Ask for a new code.", 401)

    token = secrets.token_urlsafe(32)
    with database.connect() as c:
        c.execute("DELETE FROM otp_codes WHERE phone = ? AND purpose = ?", (phone, purpose))   # works once
        c.execute("INSERT INTO sessions (token_hash, phone, kind, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                  (_hash(token), phone, purpose, now.isoformat(timespec="seconds"),
                   (now + session_length(purpose)).isoformat(timespec="seconds")))
        if purpose == VILLAGER:
            c.execute("INSERT INTO villagers (phone, village_id, created_at) VALUES (?, ?, ?) "
                      "ON CONFLICT(phone) DO UPDATE SET village_id = excluded.village_id",
                      (phone, village_id, now.isoformat(timespec="seconds")))
    user = get_official(phone) if purpose == STAFF else get_villager(phone)
    return token, user


def session_length(kind: str) -> timedelta:
    return timedelta(days=config.VILLAGER_SESSION_DAYS) if kind == VILLAGER else timedelta(hours=config.SESSION_HOURS)


# ---------- villagers ----------

def get_villager(phone: str) -> dict | None:
    with database.connect() as c:
        r = c.execute("SELECT phone, village_id FROM villagers WHERE phone = ?", (phone,)).fetchone()
        return dict(r) if r else None


# ---------- sessions ----------

def user_for_token(token: str | None, kind: str) -> dict | None:
    if not token:
        return None
    with database.connect() as c:
        r = c.execute("SELECT phone, expires_at FROM sessions WHERE token_hash = ? AND kind = ?",
                      (_hash(token), kind)).fetchone()
        if r and _now() > datetime.fromisoformat(r["expires_at"]):
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
            return None
    if not r:
        return None
    return get_official(r["phone"]) if kind == STAFF else get_villager(r["phone"])


def official_for_token(token: str | None) -> dict | None:
    return user_for_token(token, STAFF)


def end_session(token: str | None) -> None:
    if token:
        with database.connect() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


# ---------- FastAPI dependencies ----------

def require_official(request: Request) -> dict:
    """Any signed-in staff member (Gram Panchayat or NGO)."""
    user = user_for_token(request.cookies.get(COOKIES[STAFF]), STAFF)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def acts_as_gp(user: dict) -> bool:
    """Gram Panchayat officials, and the admin (who can do everything a GP can, in every taluk)."""
    return user.get("role") in ("gp", "admin")


def require_gp(request: Request) -> dict:
    """A signed-in Gram Panchayat official or the admin (approving alerts, running checks)."""
    user = require_official(request)
    if not acts_as_gp(user):
        raise HTTPException(status_code=403, detail="Only Gram Panchayat officials can do this.")
    return user


def require_admin(request: Request) -> dict:
    """The admin (set in the OFFICIALS setting with role 'admin'): gives Panchayat access to others."""
    user = require_official(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can do this.")
    return user


def require_villager(request: Request) -> dict:
    user = user_for_token(request.cookies.get(COOKIES[VILLAGER]), VILLAGER)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in with your mobile number.")
    return user
