"""Risk endpoints for dashboard staff (sign-in required; refresh is Gram Panchayat only).
Staff see the area they cover: a Gram Panchayat official their taluk, an NGO their district
(or the whole state if no area is set). Villagers never see raw risk levels; they get approved
alerts from /public."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, config
from ..auth import require_gp, require_official
from ..jobs.score_grid import score_now
from ..services.risk_view import scoped_view, taluk_risk

router = APIRouter(prefix="/risk", tags=["risk"], dependencies=[Depends(require_official)])


def _cached_or_fresh(force: bool = False) -> dict:
    """Reuse the last snapshot if it's recent; otherwise score again.
    If the forecast API is down, fall back to the last snapshot and say so."""
    f = config.LATEST_RISK_FILE
    if f.exists() and not force:
        snap = json.loads(f.read_text())
        age = datetime.now(ZoneInfo(config.TIMEZONE)) - datetime.fromisoformat(snap["generated_at"])
        if age < timedelta(minutes=config.CACHE_MINUTES) and "cells" in snap:
            return snap
    try:
        return score_now()
    except Exception as err:  # forecast API down, bad network, ...
        if f.exists():
            snap = json.loads(f.read_text())
            if "cells" in snap:                    # (an old per-village snapshot is no use)
                snap["stale"] = True
                snap["stale_reason"] = str(err)
                return snap
        raise HTTPException(status_code=503, detail=f"No risk data yet and forecast unavailable: {err}")


@router.get("")
def my_area(user: dict = Depends(require_official)):
    """Risk in the area this staff member covers: villages per level, each taluk, each rain-grid square
    (and, for one taluk, every village)."""
    return scoped_view(_cached_or_fresh(), auth.scope_taluks(user), user["area"])


@router.get("/taluk/{taluk_id}")
def one_taluk(taluk_id: str, user: dict = Depends(require_official)):
    if not auth.in_scope(user, taluk_id):
        raise HTTPException(status_code=404, detail="Not in your area.")
    snap = _cached_or_fresh()
    r = taluk_risk(snap, taluk_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Unknown taluk '{taluk_id}'")
    return {"generated_at": snap["generated_at"], "stale": snap.get("stale", False), **r}


@router.post("/refresh", dependencies=[Depends(require_gp)])
def refresh(user: dict = Depends(require_official)):
    """Ignore the cache and score the whole state now."""
    return scoped_view(_cached_or_fresh(force=True), auth.scope_taluks(user), user["area"])
