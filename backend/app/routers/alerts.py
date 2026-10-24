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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import database
from ..auth import require_gp, require_official
from ..services.alerts import draft_for, generate_for_snapshot
from .risk import _cached_or_fresh

# Every alert endpoint needs a signed-in staff member. NGOs may only READ approved alerts;
# drafting, editing and reviewing are for Gram Panchayat officials (require_gp).
router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_official)])


class EditText(BaseModel):
    message_kn: str | None = Field(None, description="New Kannada text (leave empty to keep)")
    message_en: str | None = Field(None, description="New English text (leave empty to keep)")


class Review(BaseModel):
    # The reviewer is the signed-in official, never a name typed into the request.
    note: str | None = Field(None, description="Optional for approval; required for rejection")


def _get_or_404(alert_id: int) -> dict:
    a = database.get_alert(alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"No alert {alert_id}")
    return a


@router.post("/generate", dependencies=[Depends(require_gp)])
def generate():
    """Draft alerts for all HIGH villages that don't already have one today."""
    created = generate_for_snapshot(_cached_or_fresh())
    return {"created": len(created), "alerts": created}


@router.post("/draft/{village_id}", dependencies=[Depends(require_gp)])
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
def list_all(status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
             user: dict = Depends(require_official)):
    if user["role"] != "gp":
        status = "approved"          # NGOs see only what the Gram Panchayat approved
    return database.list_alerts(status)


@router.get("/{alert_id}")
def get_one(alert_id: int, user: dict = Depends(require_official)):
    a = _get_or_404(alert_id)
    if user["role"] != "gp" and a["status"] != "approved":
        raise HTTPException(status_code=404, detail=f"No alert {alert_id}")
    return a


@router.put("/{alert_id}", dependencies=[Depends(require_gp)])
def edit(alert_id: int, body: EditText):
    _get_or_404(alert_id)
    try:
        return database.update_text(alert_id, body.message_kn, body.message_en)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))


@router.post("/{alert_id}/approve")
def approve(alert_id: int, body: Review, official: dict = Depends(require_gp)):
    _get_or_404(alert_id)
    try:
        return database.review(alert_id, "approved", official["name"], body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))


@router.post("/{alert_id}/reject")
def reject(alert_id: int, body: Review, official: dict = Depends(require_gp)):
    _get_or_404(alert_id)
    if not (body.note or "").strip():
        raise HTTPException(status_code=422, detail="Add a note saying why the alert is rejected.")
    try:
        return database.review(alert_id, "rejected", official["name"], body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))
