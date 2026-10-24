"""Risk endpoints for dashboard staff (sign-in required; refresh is Gram Panchayat only).
Villagers never see raw risk levels; they get approved alerts from /public."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..auth import require_gp, require_official
from ..jobs.score_villages import score_now

router = APIRouter(prefix="/risk", tags=["risk"], dependencies=[Depends(require_official)])


def _cached_or_fresh(force: bool = False) -> dict:
    """Reuse the last snapshot if it's recent; otherwise score again.
    If the forecast API is down, fall back to the last snapshot and say so."""
    f = config.LATEST_RISK_FILE
    if f.exists() and not force:
        snap = json.loads(f.read_text())
        age = datetime.now(ZoneInfo(config.TIMEZONE)) - datetime.fromisoformat(snap["generated_at"])
        if age < timedelta(minutes=config.CACHE_MINUTES):
            return snap
    try:
        return score_now()
    except Exception as err:  # forecast API down, bad network, ...
        if f.exists():
            snap = json.loads(f.read_text())
            snap["stale"] = True
            snap["stale_reason"] = str(err)
            return snap
        raise HTTPException(status_code=503, detail=f"No risk data yet and forecast unavailable: {err}")


@router.get("")
def all_villages():
    """Current risk for every village, most urgent first."""
    return _cached_or_fresh()


@router.get("/{village_id}")
def one_village(village_id: str):
    snap = _cached_or_fresh()
    for v in snap["villages"]:
        if v["village_id"].lower() == village_id.lower():
            return {"generated_at": snap["generated_at"], "stale": snap.get("stale", False), **v}
    raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}'")


@router.post("/refresh", dependencies=[Depends(require_gp)])
def refresh():
    """Ignore the cache and score all villages now."""
    return _cached_or_fresh(force=True)
