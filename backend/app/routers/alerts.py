"""
Alert endpoints: the Gram Panchayat reviews drafts here before villagers see them.
One alert covers one taluk. Staff only see and act on alerts in the area they cover.

Typical flow
  POST /alerts/generate          draft alerts for every HIGH taluk in your area (the scheduler does this too)
  GET  /alerts?status=pending    what's waiting for review
  PUT  /alerts/{id}              fix the wording
  POST /alerts/{id}/approve      villagers in that taluk now see it
  POST /alerts/{id}/reject       not sent; reason kept

For testing outside the monsoon, POST /alerts/draft/{taluk_id}?simulate_high=true
drafts an alert as if the taluk were HIGH, marked "simulated" so it's never shown as real.
"""
import copy

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import auth, database, push
from ..auth import require_gp, require_official
from ..services.alerts import draft_for, generate_for_snapshot
from ..services.risk_view import taluk_risk
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


def _get_or_404(alert_id: int, user: dict) -> dict:
    a = database.get_alert(alert_id)
    if a is None or not auth.in_scope(user, a["taluk_id"]) or (not auth.acts_as_gp(user) and a["status"] != "approved"):
        raise HTTPException(status_code=404, detail=f"No alert {alert_id}")
    return a


@router.post("/generate")
def generate(user: dict = Depends(require_gp)):
    """Draft alerts for all HIGH taluks in your area that don't already have one today."""
    created = generate_for_snapshot(_cached_or_fresh(), auth.scope_taluks(user))
    return {"created": len(created), "alerts": created}


@router.post("/draft/{taluk_id}")
def draft_one(taluk_id: str, simulate_high: bool = Query(False, description="Pretend the taluk is HIGH (for testing)"),
              user: dict = Depends(require_gp)):
    if not auth.in_scope(user, taluk_id):
        raise HTTPException(status_code=404, detail="Not in your area.")
    risk = taluk_risk(_cached_or_fresh(), taluk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail=f"Unknown taluk '{taluk_id}'")
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
    if not auth.acts_as_gp(user):
        status = "approved"          # NGOs see only what the Gram Panchayat approved
    return database.list_alerts(status, taluk_ids=auth.scope_taluks(user))


@router.get("/{alert_id}")
def get_one(alert_id: int, user: dict = Depends(require_official)):
    return _get_or_404(alert_id, user)


@router.put("/{alert_id}")
def edit(alert_id: int, body: EditText, user: dict = Depends(require_gp)):
    _get_or_404(alert_id, user)
    try:
        return database.update_text(alert_id, body.message_kn, body.message_en)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))


@router.post("/{alert_id}/approve")
def approve(alert_id: int, body: Review, background: BackgroundTasks, official: dict = Depends(require_gp)):
    """Publish the warning: villagers' pages show it, and every phone that turned on alarms in that taluk rings
    (Web Push; plus the taluk's public ntfy topic if set). Test alerts ring only demo-page phones."""
    _get_or_404(alert_id, official)
    try:
        a = database.review(alert_id, "approved", official["name"], body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))
    background.add_task(push.alert_villagers, a)
    return {**a, "phones_alerted": push.count([a["taluk_id"]]) if not a.get("simulated") else "demo phones only"}


@router.post("/{alert_id}/reject")
def reject(alert_id: int, body: Review, official: dict = Depends(require_gp)):
    _get_or_404(alert_id, official)
    if not (body.note or "").strip():
        raise HTTPException(status_code=422, detail="Add a note saying why the alert is rejected.")
    try:
        return database.review(alert_id, "rejected", official["name"], body.note)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err))
