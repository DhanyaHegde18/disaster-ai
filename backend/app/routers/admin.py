"""
The admin gives people access to the dashboard. Anyone may sign in as a read-only NGO guest (OPEN_SIGNIN=viewer);
only the admin can make someone a Gram Panchayat official for a taluk, or remove them.

  GET    /admin/officials          everyone with access, guests marked
  POST   /admin/officials          add someone, or change their role / area (GP needs a taluk)
  DELETE /admin/officials/{phone}  remove access (signs them out everywhere)

Admins themselves are only set in the server's OFFICIALS setting (role 'admin'), never through this page.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import areas, auth, push

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_admin)])


class Official(BaseModel):
    phone: str = Field(..., max_length=20)
    name: str = Field(..., min_length=2, max_length=60)
    role: str = Field("gp", pattern="^(gp|ngo)$")
    taluk_id: str | None = Field(None, max_length=80)
    district: str | None = Field(None, max_length=60)


def _row(o: dict) -> dict:
    return {**o, "guest": auth.is_guest(o)}


@router.get("/officials")
def officials():
    rows = [_row(o) for o in auth.list_officials()]
    return {"officials": rows, "villager_phones_with_alarms": push.count()}


@router.post("/officials")
def add(body: Official):
    if body.name.strip().startswith(auth.GUEST_PREFIX.strip()[:5]):
        raise HTTPException(status_code=422, detail="Give the person's real name (guests get codes on screen; "
                                                    "staff get them by ntfy).")
    if body.role == "gp" and not body.taluk_id:
        raise HTTPException(status_code=422, detail="A Gram Panchayat official needs a taluk.")
    if body.taluk_id and not areas.get().taluk(body.taluk_id):
        raise HTTPException(status_code=422, detail=f"Unknown taluk '{body.taluk_id}'.")
    try:
        existing = auth.get_official(auth.normalize_phone(body.phone))
        if existing and existing["role"] == "admin":
            raise HTTPException(status_code=403, detail="Admins are changed only in the server's OFFICIALS setting.")
        o = auth.add_official(body.phone, body.name, body.role, taluk_id=body.taluk_id if body.role == "gp" else None,
                              district=None if body.role == "gp" else body.district)
    except auth.AuthError as err:
        raise HTTPException(status_code=err.status, detail=str(err))
    return _row(o)


@router.delete("/officials/{phone}")
def remove(phone: str, me: dict = Depends(auth.require_admin)):
    try:
        target = auth.get_official(auth.normalize_phone(phone))
    except auth.AuthError as err:
        raise HTTPException(status_code=err.status, detail=str(err))
    if not target:
        raise HTTPException(status_code=404, detail="No such staff member.")
    if target["role"] == "admin":
        raise HTTPException(status_code=403, detail="Admins are removed only in the server's OFFICIALS setting.")
    return {"removed": auth.remove_official(phone)}
