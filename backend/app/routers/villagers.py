"""
Villager sign-in and family evacuation reports (used by the villager page).

Seeing warnings never needs a sign-in (/public/status). Signing in is only for SENDING
a report, so the Gram Panchayat knows which family it came from and can follow up.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .. import areas, auth, config, database, notify
from .auth import fail, set_session_cookie

router = APIRouter(prefix="/public", tags=["villagers"])

NEEDS = ("rescue", "food", "water", "medicine", "elderly_help")


class PhoneIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: str
    village_id: str


class ReportIn(BaseModel):
    village_id: str
    at_shelter: int = Field(0, ge=0, le=50, description="People at a relief centre (ಕಾಳಜಿ ಕೇಂದ್ರ)")
    with_relatives: int = Field(0, ge=0, le=50, description="People with relatives / in another village")
    at_home: int = Field(0, ge=0, le=50, description="People who stayed at home")
    unknown: int = Field(0, ge=0, le=50, description="People whose whereabouts are unknown")
    needs: list[str] = Field(default_factory=list, description=f"Any of: {', '.join(NEEDS)}")
    queued_at: str | None = Field(None, description="When the report was written, if the phone had no network "
                                                    "and is sending it later (ISO time)")

    @field_validator("queued_at")
    @classmethod
    def sensible_time(cls, v):
        if v is None:
            return None
        try:
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("queued_at must be an ISO date-time")
        if t.tzinfo is None:
            t = t.replace(tzinfo=ZoneInfo(config.TIMEZONE))
        now = datetime.now(ZoneInfo(config.TIMEZONE))
        if t > now + timedelta(minutes=10) or t < now - timedelta(days=3):
            return None                   # phone clock is off or it's too old: treat as written now
        return t.astimezone(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds")

    @field_validator("needs")
    @classmethod
    def known_needs(cls, v):
        bad = [n for n in v if n not in NEEDS]
        if bad:
            raise ValueError(f"Unknown needs: {bad}. Allowed: {NEEDS}")
        return sorted(set(v))


def latest_report(phone: str) -> dict | None:
    with database.connect() as c:
        r = c.execute("SELECT * FROM evacuation_reports WHERE phone = ?", (phone,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d.pop("phone")
    d["needs"] = json.loads(d["needs"])
    return d


@router.post("/auth/request-code")
def request_code(body: PhoneIn):
    try:
        return auth.request_code(body.phone, auth.VILLAGER)
    except auth.AuthError as err:
        fail(err)


@router.post("/auth/verify")
def verify(body: VerifyIn, request: Request, response: Response):
    try:
        token, user = auth.verify_code(body.phone, body.code, auth.VILLAGER, body.village_id)
    except auth.AuthError as err:
        fail(err)
    set_session_cookie(response, auth.VILLAGER, token, request)
    return {"phone": auth.mask(user["phone"]), "village_id": user["village_id"]}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.COOKIES[auth.VILLAGER]))
    response.delete_cookie(auth.COOKIES[auth.VILLAGER], path="/")
    return {"signed_out": True}


@router.get("/me")
def me(user: dict = Depends(auth.require_villager)):
    v = areas.get().village(user["village_id"])
    return {"phone": auth.mask(user["phone"]), "village_id": user["village_id"],
            "village_name": v["name"] if v else None, "report": latest_report(user["phone"])}


@router.post("/report")
def report(body: ReportIn, background: BackgroundTasks, user: dict = Depends(auth.require_villager)):
    """Send (or update) this family's evacuation status. A rescue request alerts staff phones."""
    if not areas.get().village(body.village_id):
        raise HTTPException(status_code=422, detail="Unknown village.")
    if body.at_shelter + body.with_relatives + body.at_home + body.unknown == 0:
        raise HTTPException(status_code=422, detail="Report at least one person.")
    with database.connect() as c:
        c.execute("""INSERT INTO evacuation_reports
                       (phone, village_id, at_shelter, with_relatives, at_home, unknown, needs, reported_at, queued_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(phone) DO UPDATE SET village_id = excluded.village_id,
                       at_shelter = excluded.at_shelter, with_relatives = excluded.with_relatives,
                       at_home = excluded.at_home, unknown = excluded.unknown,
                       needs = excluded.needs, reported_at = excluded.reported_at,
                       handled_by = NULL, handled_at = NULL, queued_at = excluded.queued_at""",
                  (user["phone"], body.village_id, body.at_shelter, body.with_relatives, body.at_home,
                   body.unknown, json.dumps(body.needs), database.now(), body.queued_at))
        c.execute("UPDATE villagers SET village_id = ? WHERE phone = ?", (body.village_id, user["phone"]))
    saved = latest_report(user["phone"])
    if "rescue" in body.needs:     # rings that taluk's GP phones and the district's NGOs
        background.add_task(notify.notify_rescue, {"phone": user["phone"], **saved})
    return {"saved": True, "report": saved}
