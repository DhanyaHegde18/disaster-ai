"""
Sending sign-in codes by SMS. Pick the provider with SMS_PROVIDER in .env.

  demo      No SMS. The code is returned to the sign-in screen.
  twilio    Twilio Verify. Twilio creates, sends AND checks the code, so we never see it.
            Free trial: 40 verifications, only to numbers you verified in the Twilio console.
  fast2sms  Fast2SMS OTP route. We create the code; Fast2SMS sends it to any Indian number.
            Paid per SMS. Check their dashboard for the current price and DLT rules.

Why India makes SMS awkward: TRAI's DLT rules require businesses to register sender IDs and
message templates. Twilio's trial and Fast2SMS's OTP route are the simplest ways around that
for a student project.
"""
import requests

from . import config


class SMSError(Exception):
    pass


def _check_config(*names: str) -> None:
    missing = [n for n in names if not getattr(config, n)]
    if missing:
        raise SMSError(f"SMS_PROVIDER={config.SMS_PROVIDER} needs {', '.join(missing)} in .env")


# ---------- Twilio Verify ----------
TWILIO_VERIFY = "https://verify.twilio.com/v2/Services/{sid}/{resource}"


def _twilio(resource: str, data: dict) -> dict:
    _check_config("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SID")
    try:
        r = requests.post(TWILIO_VERIFY.format(sid=config.TWILIO_VERIFY_SID, resource=resource),
                          data=data, auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
                          timeout=config.SMS_TIMEOUT_S)
    except requests.RequestException as err:
        raise SMSError(f"Could not reach Twilio: {type(err).__name__}")
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except ValueError:
            msg = r.text
        raise SMSError(f"Twilio refused ({r.status_code}): {msg[:200]}")
    return r.json()


def twilio_start(phone: str) -> None:
    """Ask Twilio to text a code to `phone` (E.164, e.g. +919876543210)."""
    _twilio("Verifications", {"To": phone, "Channel": "sms"})


def twilio_check(phone: str, code: str) -> bool:
    """True if `code` is the one Twilio sent."""
    try:
        return _twilio("VerificationCheck", {"To": phone, "Code": code}).get("status") == "approved"
    except SMSError as err:
        # Twilio answers 404 once a verification has expired or was already used.
        if "(404)" in str(err):
            return False
        raise


# ---------- Fast2SMS ----------
FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"


def fast2sms_send(phone: str, code: str) -> None:
    """Send `code` using Fast2SMS's OTP route (their fixed 'Your OTP is ...' message)."""
    _check_config("FAST2SMS_API_KEY")
    try:
        r = requests.post(FAST2SMS_URL, headers={"authorization": config.FAST2SMS_API_KEY},
                          json={"route": "otp", "variables_values": code, "numbers": phone[-10:]},
                          timeout=config.SMS_TIMEOUT_S)
        body = r.json()
    except (requests.RequestException, ValueError) as err:
        raise SMSError(f"Could not reach Fast2SMS: {type(err).__name__}")
    if r.status_code >= 400 or not body.get("return"):
        msg = body.get("message") if isinstance(body, dict) else r.text
        raise SMSError(f"Fast2SMS refused: {msg}")
