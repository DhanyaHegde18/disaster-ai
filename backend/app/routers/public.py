"""
Public endpoints for villagers (no sign-in).

  GET /public/districts               districts (with Kannada names) and their taluks
  GET /public/villages?taluk_id=&q=   villages in a taluk, or a name search (spelling-tolerant)
  GET /public/village/{id}            one village
  GET /public/status/{village_id}     warnings for that village's taluk

Rule: villagers only ever see alerts a Gram Panchayat member has APPROVED.
No pending drafts, no rejected alerts, no raw risk levels from the engine, and no
simulated test alerts unless the page is opened in demo mode (?demo=true).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import areas, config, database, push

router = APIRouter(prefix="/public", tags=["public (villagers)"])

ACTIVE_HOURS = 24   # an approved alert counts as "active" for this long after approval


def village_or_404(village_id: str) -> dict:
    v = areas.get().village(village_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}'")
    return v


def village_view(v: dict) -> dict:
    a = areas.get()
    t = a.taluk(v["taluk_id"]) or {}
    return {**areas.public(v), "district_kn": a.district_kn.get(v["district"]), "taluk_kn": t.get("name_kn")}


@router.get("/districts")
def districts():
    return areas.get().districts


@router.get("/villages")
def villages(taluk_id: str | None = None, district: str | None = None,
             q: str = Query("", max_length=60, description="Village name (any spelling)"),
             limit: int = Query(30, ge=1, le=600)):
    """Villages in a taluk (all of them if no q), or a search by name across a district / the state."""
    a = areas.get()
    if taluk_id and not a.taluk(taluk_id):
        raise HTTPException(status_code=404, detail=f"Unknown taluk '{taluk_id}'")
    if not taluk_id and not q.strip():
        raise HTTPException(status_code=422, detail="Give a taluk_id or a name to search for.")
    found = a.search(q, taluk_id=taluk_id, district=district, limit=limit)
    return [{**{k: v[k] for k in ("village_id", "name", "name_kn", "taluk", "taluk_id", "district")},
             "taluk_kn": (a.taluk(v["taluk_id"]) or {}).get("name_kn")} for v in found]


@router.get("/village/{village_id}")
def village(village_id: str):
    return village_view(village_or_404(village_id))


@router.get("/status/{village_id}")
def status(village_id: str, demo: bool = Query(False, description="Also show simulated test alerts, labelled as tests")):
    """Approved alerts for the village's taluk: `active` (approved in the last 24 h) and `recent` (last 7 days)."""
    v = village_or_404(village_id)
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    active, recent = [], []
    for al in database.list_public_alerts(v["taluk_id"], include_simulated=demo):
        item = {
            "id": al["id"],
            "message_kn": al["message_kn"],
            "message_en": al["message_en"],
            "approved_at": al["reviewed_at"],
            "approved_by": al["reviewed_by"],
            "test": al["simulated"],
        }
        is_active = now - datetime.fromisoformat(al["reviewed_at"]) < timedelta(hours=ACTIVE_HOURS)
        (active if is_active else recent).append(item)
    return {
        "village": village_view(v),
        "checked_at": now.isoformat(timespec="seconds"),
        "active": active,
        "recent": recent,
        "emergency_number": config.EMERGENCY_NUMBER,
    }


# ---------- alarms on villagers' phones (Web Push) ----------

class PushSubscription(BaseModel):
    subscription: dict
    village_id: str = Field(..., max_length=40)
    lang: str = Field("kn", max_length=5)
    demo: bool = False


class PushEndpoint(BaseModel):
    endpoint: str = Field(..., max_length=1000)


@router.get("/push/key")
def push_key():
    """The public key the villager page needs to ask the browser for a push subscription."""
    return {"public_key": push.keys()[0]}


@router.post("/push/subscribe")
def push_subscribe(body: PushSubscription):
    """This phone wants warnings for its village's taluk, even when the page is closed."""
    try:
        return push.subscribe(body.subscription, body.village_id, body.lang, body.demo)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))


@router.post("/push/unsubscribe")
def push_unsubscribe(body: PushEndpoint):
    return {"removed": push.unsubscribe(body.endpoint)}


@router.get("/push/topic/{village_id}")
def push_topic(village_id: str):
    """The public ntfy topic for loud alarms in this village's taluk (null if the server has none)."""
    v = village_or_404(village_id)
    return {"topic": push.public_topic(v["taluk_id"]), "server": config.NTFY_SERVER}
