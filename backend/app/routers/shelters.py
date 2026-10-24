"""
Relief centres (ಕಾಳಜಿ ಕೇಂದ್ರ).

  GET   /public/shelters/{village}   anyone: nearest DESIGNATED centres, open ones within reach first.
                                     ?lat=&lon= measures from the person's own location.
  GET   /shelters                    staff: designated centres in your area, with head counts, and how many
                                     people told us (in family reports) they're at a centre
  GET   /shelters/candidates         staff: possible centres from OpenStreetMap in your area (?q= to search)
  POST  /shelters                    Gram Panchayat: add a centre at a map point
  PATCH /shelters/{id}               Gram Panchayat: designate a candidate (with capacity), open/close,
                                     set people inside, phone number
"""
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import areas, auth, config, notify
from ..services import shelters
from .public import village_or_404
from .relief import reports_in_scope

public_router = APIRouter(prefix="/public", tags=["public (villagers)"])
router = APIRouter(prefix="/shelters", tags=["relief centres"])

PUBLIC_FIELDS = ("shelter_id", "name", "name_kn", "kind", "lat", "lon", "capacity", "occupancy", "spaces_left",
                 "status", "phone", "updated_at", "distance_km", "reachable", "taluk_id")


@public_router.get("/shelters/{village_id}")
def nearest_shelters(village_id: str,
                     lat: float | None = Query(None, ge=-90, le=90, description="Your location (optional)"),
                     lon: float | None = Query(None, ge=-180, le=180),
                     limit: int = Query(3, ge=1, le=10)):
    v = village_or_404(village_id)
    mine = lat is not None and lon is not None
    found = shelters.nearest(*((lat, lon) if mine else (v["lat"], v["lon"])), limit=limit)
    return {
        "village_id": v["village_id"],
        "measured_from": "your_location" if mine else "village_centre",
        "any_open": any(s["reachable"] for s in found),      # an open centre within reach
        "shelters": [{k: s.get(k) for k in PUBLIC_FIELDS} for s in found],
        "emergency_number": config.EMERGENCY_NUMBER,
    }


def _check_scope(user: dict, s: dict | None) -> dict:
    if s is None or not auth.in_scope(user, s.get("taluk_id")):
        raise HTTPException(status_code=404, detail="No such relief centre in your area.")
    return s


@router.get("")
def my_centres(user: dict = Depends(auth.require_official)):
    scope = auth.scope_taluks(user)
    items = shelters.in_taluks(scope, designated=True)
    reported = defaultdict(int)
    for r, v in reports_in_scope(user):
        reported[v["taluk_id"]] += r["at_shelter"]
    a = areas.get()
    taluk_ids = sorted(scope) if scope is not None else sorted({s["taluk_id"] for s in items} | set(reported))
    groups = []
    for tid in taluk_ids:
        t = a.taluk(tid) or {"name": tid, "district": ""}
        groups.append({"taluk_id": tid, "name": t["name"], "district": t["district"],
                       "reported_at_shelter": reported.get(tid, 0),
                       "shelters": [s for s in items if s["taluk_id"] == tid]})
    open_ = [s for s in items if s["is_open"]]
    return {
        "area": user["area"],
        "totals": {"centres": len(items), "open": len(open_), "people": sum(s["occupancy"] for s in open_),
                   "places": sum(s["capacity"] for s in open_), "full": sum(s["status"] == "full" for s in items),
                   "candidates": len(shelters.in_taluks(scope, designated=False, limit=100000)) if scope is not None else None},
        "taluks": groups,
    }


@router.get("/candidates")
def candidates(q: str = Query("", max_length=60), limit: int = Query(500, ge=1, le=2000),
               user: dict = Depends(auth.require_official)):
    """Schools, community halls and GP offices from OpenStreetMap that could serve as centres."""
    scope = auth.scope_taluks(user)
    if scope is None and not q.strip():
        raise HTTPException(status_code=422, detail="State-wide: search by name (q=...).")
    return shelters.in_taluks(scope, designated=False, q=q, limit=limit)


class NewCentre(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    name_kn: str | None = Field(None, max_length=120)
    lat: float = Field(..., ge=11.0, le=19.0)
    lon: float = Field(..., ge=74.0, le=79.0)
    capacity: int = Field(..., ge=1, le=5000)
    phone: str | None = Field(None, max_length=20)


@router.post("")
def add_centre(body: NewCentre, user: dict = Depends(auth.require_gp)):
    v = areas.get().nearest_village(body.lat, body.lon)
    if not v or not auth.in_scope(user, v["taluk_id"]):
        raise HTTPException(status_code=403, detail="That point is outside your taluk.")
    try:
        return shelters.add(user["name"], body.name, body.lat, body.lon, body.capacity, body.name_kn, body.phone)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))


class ShelterUpdate(BaseModel):
    designated: bool | None = Field(None, description="Mark a possible centre as a relief centre (needs capacity)")
    capacity: int | None = Field(None, ge=1, le=5000)
    is_open: bool | None = None
    occupancy: int | None = Field(None, ge=0, le=5000, description="People inside right now")
    phone: str | None = Field(None, max_length=20)


@router.patch("/{shelter_id}")
def update_shelter(shelter_id: str, body: ShelterUpdate, background: BackgroundTasks,
                   user: dict = Depends(auth.require_gp)):
    if not body.model_dump(exclude_none=True):
        raise HTTPException(status_code=422, detail="Nothing to change.")
    _check_scope(user, shelters.get(shelter_id))
    try:
        before, after = shelters.update(shelter_id, user["name"], body.is_open, body.occupancy,
                                        body.designated, body.capacity, body.phone)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))
    background.add_task(notify.notify_shelter_change, before, after)   # phone push, after replying
    return after
