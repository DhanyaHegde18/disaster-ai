"""Sign-in endpoints for dashboard staff (Gram Panchayat officials and NGOs)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, config, notify

router = APIRouter(prefix="/auth", tags=["sign-in (staff)"])


class PhoneIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: str


def fail(err: auth.AuthError):
    raise HTTPException(status_code=err.status, detail=str(err))


def set_session_cookie(response: Response, kind: str, token: str, request: Request | None = None) -> None:
    """httpOnly + SameSite=Strict always; https-only when the page came over https (or COOKIE_SECURE=true),
    so the same server works on localhost, on the Wi-Fi address and through an https tunnel."""
    https = request is not None and notify.request_base(request)[0] == "https"
    response.set_cookie(auth.COOKIES[kind], token, max_age=int(auth.session_length(kind).total_seconds()), httponly=True,
                        samesite="strict", secure=config.COOKIE_SECURE or https, path="/")


def staff_view(user: dict) -> dict:
    """Who is signed in, the area they cover, and the ntfy topic for their phone (only shown to them)."""
    return {"name": user["name"], "role": user["role"], "phone": auth.mask(user["phone"]),
            "area": user["area"], "district": user.get("district"), "taluk_id": user.get("taluk_id"),
            "taluk_name": user.get("taluk_name"), "alert_topic": notify.topic_for_user(user),
            "ntfy_server": config.NTFY_SERVER}


@router.post("/request-code")
def request_code(body: PhoneIn):
    """Send a 6-digit sign-in code (shown on screen in demo mode)."""
    try:
        return auth.request_code(body.phone, auth.STAFF)
    except auth.AuthError as err:
        fail(err)


@router.post("/verify")
def verify(body: VerifyIn, request: Request, response: Response):
    """Check the code and start a session (httpOnly cookie)."""
    try:
        token, user = auth.verify_code(body.phone, body.code, auth.STAFF)
    except auth.AuthError as err:
        fail(err)
    set_session_cookie(response, auth.STAFF, token, request)
    notify.learn_public_url(request)
    return staff_view(user)


@router.get("/me")
def me(request: Request, user: dict = Depends(auth.require_official)):
    notify.learn_public_url(request)        # links in phone notifications follow the address staff use
    return staff_view(user)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.COOKIES[auth.STAFF]))
    response.delete_cookie(auth.COOKIES[auth.STAFF], path="/")
    return {"signed_out": True}
