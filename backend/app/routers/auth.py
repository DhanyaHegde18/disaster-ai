"""Sign-in endpoints for dashboard staff (Gram Panchayat officials and NGOs)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, config

router = APIRouter(prefix="/auth", tags=["sign-in (staff)"])


class PhoneIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: str


def fail(err: auth.AuthError):
    raise HTTPException(status_code=err.status, detail=str(err))


def set_session_cookie(response: Response, kind: str, token: str) -> None:
    response.set_cookie(auth.COOKIES[kind], token, max_age=config.SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", secure=config.COOKIE_SECURE, path="/")


def staff_view(user: dict) -> dict:
    return {"name": user["name"], "role": user["role"], "phone": auth.mask(user["phone"])}


@router.post("/request-code")
def request_code(body: PhoneIn):
    """Send a 6-digit sign-in code (shown on screen in demo mode)."""
    try:
        return auth.request_code(body.phone, auth.STAFF)
    except auth.AuthError as err:
        fail(err)


@router.post("/verify")
def verify(body: VerifyIn, response: Response):
    """Check the code and start a session (httpOnly cookie)."""
    try:
        token, user = auth.verify_code(body.phone, body.code, auth.STAFF)
    except auth.AuthError as err:
        fail(err)
    set_session_cookie(response, auth.STAFF, token)
    return staff_view(user)


@router.get("/me")
def me(user: dict = Depends(auth.require_official)):
    return staff_view(user)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.COOKIES[auth.STAFF]))
    response.delete_cookie(auth.COOKIES[auth.STAFF], path="/")
    return {"signed_out": True}
