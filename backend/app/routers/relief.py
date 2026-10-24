"""
Relief coordination for staff: where people are, per village, from villagers' reports.
Everything is limited to the area the staff member covers (their taluk / district).

  GET  /relief/summary                Gram Panchayat AND NGOs: counts per village that has reports, no personal data
  GET  /relief/reports/{village}      Gram Panchayat only: each family's report WITH phone number,
                                      so officials can call families who asked for rescue or reported
                                      someone missing. NGOs never get phone numbers, only the counts.
  POST /relief/reports/{phone}/handled  Gram Panchayat only: rescue dealt with, stop the reminders
Only reports from the last REPORT_DAYS days count, so an old flood doesn't linger.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import areas, auth, config, database

router = APIRouter(prefix="/relief", tags=["relief"])
REPORT_DAYS = 3
CATEGORIES = ("at_shelter", "with_relatives", "at_home", "unknown")


def _since(days: int) -> str:
    return (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)).isoformat(timespec="seconds")


def reports_in_scope(user: dict, days: int = REPORT_DAYS) -> list[tuple[dict, dict]]:
    """(report row, village) pairs from the last `days` days in the user's area."""
    a = areas.get()
    with database.connect() as c:
        rows = c.execute("SELECT * FROM evacuation_reports WHERE reported_at >= ?", (_since(days),)).fetchall()
    out = []
    for r in rows:
        v = a.village(r["village_id"])
        if v and auth.in_scope(user, v["taluk_id"]):
            out.append((dict(r), v))
    return out


@router.get("/summary")
def summary(days: int = Query(REPORT_DAYS, ge=1, le=30), user: dict = Depends(auth.require_official)):
    out = {}
    for r, v in reports_in_scope(user, days):
        s = out.setdefault(v["village_id"], {
            "village_id": v["village_id"], "name": v["name"], "name_kn": v.get("name_kn"), "taluk": v["taluk"],
            "families": 0, **{c: 0 for c in CATEGORIES}, "needs": {}, "rescue_requests": 0, "rescue_handled": 0,
            "last_report_at": None})
        s["families"] += 1
        for cat in CATEGORIES:
            s[cat] += r[cat]
        needs = json.loads(r["needs"])
        for need in needs:
            s["needs"][need] = s["needs"].get(need, 0) + 1
        if "rescue" in needs:       # open = nobody has dealt with it yet
            s["rescue_handled" if r["handled_at"] else "rescue_requests"] += 1
        s["last_report_at"] = max(filter(None, [s["last_report_at"], r["reported_at"]]))
    villages_out = sorted(out.values(), key=lambda s: (-s["rescue_requests"], -s["unknown"], -s["families"], s["name"]))
    totals = {c: sum(s[c] for s in villages_out)
              for c in (*CATEGORIES, "families", "rescue_requests", "rescue_handled")}
    return {"days": days, "area": user["area"], "totals": totals, "villages": villages_out}


@router.get("/reports/{village_id}")
def family_reports(village_id: str, days: int = Query(REPORT_DAYS, ge=1, le=30),
                   user: dict = Depends(auth.require_gp)):
    v = areas.get().village(village_id)
    if not v or not auth.in_scope(user, v["taluk_id"]):
        raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}' (or not in your taluk)")
    with database.connect() as c:
        rows = c.execute("SELECT * FROM evacuation_reports WHERE village_id = ? AND reported_at >= ? "
                         "ORDER BY reported_at DESC", (village_id, _since(days))).fetchall()
    families = []
    for r in rows:
        d = dict(r)
        d["needs"] = json.loads(d["needs"])
        families.append(d)
    # Open rescue requests first, then missing people: those need a phone call now.
    families.sort(key=lambda f: ("rescue" not in f["needs"] or bool(f["handled_at"]), f["unknown"] == 0))
    return {"village_id": village_id, "families": families}


@router.post("/reports/{phone}/handled")
def mark_handled(phone: str, user: dict = Depends(auth.require_gp)):
    """A Gram Panchayat official has called the family / sent help: stop the rescue reminders."""
    try:
        phone = auth.normalize_phone(phone)
    except auth.AuthError as err:
        raise HTTPException(status_code=422, detail=str(err))
    with database.connect() as c:
        r = c.execute("SELECT village_id, needs, handled_at FROM evacuation_reports WHERE phone = ?", (phone,)).fetchone()
    v = areas.get().village(r["village_id"]) if r else None
    if not r or "rescue" not in json.loads(r["needs"]) or not v or not auth.in_scope(user, v["taluk_id"]):
        raise HTTPException(status_code=404, detail="No rescue request from this number in your taluk.")
    if not r["handled_at"]:
        with database.connect() as c:
            c.execute("UPDATE evacuation_reports SET handled_by = ?, handled_at = ? WHERE phone = ?",
                      (user["name"], database.now(), phone))
    return {"handled": True, "by": user["name"]}
