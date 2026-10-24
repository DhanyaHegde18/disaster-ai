"""
Relief coordination for staff: where people are, per village, from villagers' reports.

  GET /relief/summary            Gram Panchayat AND NGOs: counts per village, no personal data
  GET /relief/reports/{village}  Gram Panchayat only: each family's report WITH phone number,
                                 so officials can call families who asked for rescue or reported
                                 someone missing. NGOs never get phone numbers, only the counts.
Only reports from the last REPORT_DAYS days count, so an old flood doesn't linger.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import auth, config, database

router = APIRouter(prefix="/relief", tags=["relief"])
REPORT_DAYS = 3
CATEGORIES = ("at_shelter", "with_relatives", "at_home", "unknown")


def _since(days: int) -> str:
    return (datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(days=days)).isoformat(timespec="seconds")


@router.get("/summary")
def summary(days: int = Query(REPORT_DAYS, ge=1, le=30), user: dict = Depends(auth.require_official)):
    villages = {v["village_id"]: v for v in config.rule_config()["villages"]}
    out = {vid: {"village_id": vid, "name": v["name"], "name_kn": v.get("name_kn"), "families": 0,
                 **{c: 0 for c in CATEGORIES}, "needs": {}, "rescue_requests": 0, "rescue_handled": 0,
                 "last_report_at": None}
           for vid, v in villages.items()}
    with database.connect() as c:
        rows = c.execute("SELECT * FROM evacuation_reports WHERE reported_at >= ?", (_since(days),)).fetchall()
    for r in rows:
        s = out.get(r["village_id"])
        if not s:
            continue
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
    return {"days": days, "totals": totals, "villages": villages_out}


@router.get("/reports/{village_id}")
def family_reports(village_id: str, days: int = Query(REPORT_DAYS, ge=1, le=30),
                   user: dict = Depends(auth.require_gp)):
    ids = {v["village_id"].lower(): v["village_id"] for v in config.rule_config()["villages"]}
    vid = ids.get(village_id.lower())
    if not vid:
        raise HTTPException(status_code=404, detail=f"Unknown village '{village_id}'")
    with database.connect() as c:
        rows = c.execute("SELECT * FROM evacuation_reports WHERE village_id = ? AND reported_at >= ? "
                         "ORDER BY reported_at DESC", (vid, _since(days))).fetchall()
    families = []
    for r in rows:
        d = dict(r)
        d["needs"] = json.loads(d["needs"])
        families.append(d)
    # Open rescue requests first, then missing people: those need a phone call now.
    families.sort(key=lambda f: ("rescue" not in f["needs"] or bool(f["handled_at"]), f["unknown"] == 0))
    return {"village_id": vid, "families": families}


@router.post("/reports/{phone}/handled")
def mark_handled(phone: str, user: dict = Depends(auth.require_gp)):
    """A Gram Panchayat official has called the family / sent help: stop the rescue reminders."""
    try:
        phone = auth.normalize_phone(phone)
    except auth.AuthError as err:
        raise HTTPException(status_code=422, detail=str(err))
    with database.connect() as c:
        r = c.execute("SELECT needs, handled_at FROM evacuation_reports WHERE phone = ?", (phone,)).fetchone()
        if not r or "rescue" not in json.loads(r["needs"]):
            raise HTTPException(status_code=404, detail="No rescue request from this number.")
        if not r["handled_at"]:
            c.execute("UPDATE evacuation_reports SET handled_by = ?, handled_at = ? WHERE phone = ?",
                      (user["name"], database.now(), phone))
    return {"handled": True, "by": user["name"]}
