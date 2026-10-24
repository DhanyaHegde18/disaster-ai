"""
Public endpoints for villagers.

Rule: villagers only ever see alerts a Gram Panchayat member has APPROVED.
No pending drafts, no rejected alerts, no raw risk levels from the engine, and no
simulated test alerts unless the page is opened in demo mode (?demo=true).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from .. import config, database

router = APIRouter(prefix="/public", tags=["public (villagers)"])

ACTIVE_HOURS = 24   # an approved alert counts as "active" for this long after approval


def _village(village_id: str) -> dict:
    for v in config.rule_config()["villages"]:
        if v["village_id"].lower() == village_id.lower():
            return v
    raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}'")


@router.get("/villages")
def villages():
    """Village list for the villager page's picker."""
    return [{k: v.get(k) for k in ("village_id", "name", "name_kn", "district")}
            for v in config.rule_config()["villages"]]


@router.get("/status/{village_id}")
def status(village_id: str, demo: bool = Query(False, description="Also show simulated test alerts, labelled as tests")):
    """Approved alerts for one village: `active` (approved in the last 24 h) and `recent` (last 7 days)."""
    v = _village(village_id)
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    active, recent = [], []
    for a in database.list_public_alerts(v["village_id"], include_simulated=demo):
        item = {
            "id": a["id"],
            "message_kn": a["message_kn"],
            "message_en": a["message_en"],
            "approved_at": a["reviewed_at"],
            "approved_by": a["reviewed_by"],
            "test": a["simulated"],
        }
        is_active = now - datetime.fromisoformat(a["reviewed_at"]) < timedelta(hours=ACTIVE_HOURS)
        (active if is_active else recent).append(item)
    return {
        "village": {k: v.get(k) for k in ("village_id", "name", "name_kn", "district")},
        "checked_at": now.isoformat(timespec="seconds"),
        "active": active,
        "recent": recent,
        "emergency_number": config.EMERGENCY_NUMBER,
    }
