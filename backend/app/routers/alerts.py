"""
Alert endpoints: the Gram Panchayat reviews drafts here before villagers see them.

Typical flow
  POST /alerts/generate          draft alerts for every HIGH village (the scheduled job does this too)
  GET  /alerts?status=pending    what's waiting for review
  PUT  /alerts/{id}              fix the wording
  POST /alerts/{id}/approve      villager app may now show it
  POST /alerts/{id}/reject       not sent; reason kept

For testing outside the monsoon, POST /alerts/draft/{village_id}?simulate_high=true
drafts an alert as if the village were HIGH, marked "simulated" so it's never shown as real.
"""
import copy

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import database
from ..services.alerts import draft_for, generate_for_snapshot
from .risk import _cached_or_fresh

router = APIRouter(prefix="/alerts", tags=["alerts"])


class EditText(BaseModel):
    message_kn: str | None = Field(None, description="New Kannada text (leave empty to keep)")
    message_en: str | None = Field(None, description="New English text (leave empty to keep)")


class Review(BaseModel):
    reviewed_by: str = Field(..., min_length=2, description="Name or role of the reviewer, e.g. 'Ujire GP secretary'")
    note: str | None = Field(None, description="Optional comment (required in spirit for rejections)")


def _get_or_404(alert_id: int) -> dict:
    a = database.get_alert(alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"No alert {alert_id}")
    return a


@router.post("/generate")
def generate():
    """Draft alerts for all HIGH villages that don't already have one today."""
    created = generate_for_snapshot(_cached_or_fresh())
    return {"created": len(created), "alerts": created}


@router.post("/draft/{village_id}")
def draft_one(village_id: str, simulate_high: bool = Query(False, description="Pretend the village is HIGH (for testing)")):
    snap = _cached_or_fresh()
    risk = next((v for v in snap["villages"] if v["village_id"].lower() == village_id.lower()), None)
    if risk is None:
        raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}'")
    if simulate_high:
        risk = copy.deepcopy(risk)
        risk["level"] = "HIGH"
        # Give the drafter a plausible heavy-rain story; the stored alert is flagged as simulated.
        risk["forecast_3d_mm"] = max(risk["forecast_3d_mm"], 250.0)
        risk["reasons"] = ["SIMULATED for testing: forecast set to at least 250 mm"]
    elif risk["level"] == "LOW":
        raise HTTPException(status_code=409, detail=f"{risk['name']} is LOW right now. "
                                                    "Use ?simulate_high=true to test drafting.")
    return draft_for(risk, simulated=simulate_high)


@router.get("")
def list_all(status: str | None = Query(None, pattern="^(pending|approved|rejected)$")):
    return database.list_alerts(status)


@router.get("/{alert_id}")
def get_one(alert_id: int):
    return _get_or_404(alert_id)


@router.put("/{alert_id}")
def edit(alert_id: int, body: EditText):
    _get_or_404(alert_id)
    try:
        return database.update_text(alert_id, body.message_kn, body.message_en)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))


@router.post("/{alert_id}/approve")
def approve(alert_id: int, body: Review):
    _get_or_404(alert_id)
    try:
        return database.review(alert_id, "approved", body.reviewed_by, body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))


@router.post("/{alert_id}/reject")
def reject(alert_id: int, body: Review):
    _get_or_404(alert_id)
    try:
        return database.review(alert_id, "rejected", body.reviewed_by, body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))
