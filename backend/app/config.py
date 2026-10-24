"""Settings for the backend. Change values here, not inside the services."""
import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")  # secrets like GEMINI_API_KEY live in .env (git-ignored)

RULE_CONFIG = APP_DIR / "rule_config.json"          # written by ml/scripts/calibrate_rule.py
LATEST_RISK_FILE = BACKEND_DIR / "data" / "latest_risk.json"
ALERTS_DB = BACKEND_DIR / "data" / "alerts.db"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Kolkata"
CACHE_MINUTES = 60          # /risk reuses results younger than this instead of calling the API again
REQUEST_TIMEOUT_S = 30
RETRIES = 3

# Gemini (alert drafting). Without a key, alerts use the fixed bilingual template.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")  # used if the main one is busy
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_TIMEOUT_S = 25      # per request; if a model is silent this long, move on to the backup
GEMINI_BUSY_RETRIES = 2     # extra tries per model on 429/500/503
GEMINI_RETRY_WAIT_S = 3     # waits 3 s, then 6 s

# Automatic scoring while the server runs (see jobs/scheduler.py)
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
SCORING_INTERVAL_MIN = float(os.getenv("SCORING_INTERVAL_MIN", "180"))   # every 3 hours
SCHEDULER_FIRST_RUN_DELAY_S = 30   # wait a little after startup before the first run

# Sign-in codes by SMS. SMS_PROVIDER:
#   demo      code shown on screen (no SMS; for development and demos)
#   twilio    Twilio Verify (free trial: up to 5 verified numbers, 30 days)
#   fast2sms  Fast2SMS OTP route (any Indian number, paid per SMS)
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "demo").strip().lower()
OTP_DEMO_MODE = SMS_PROVIDER == "demo"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_VERIFY_SID = os.getenv("TWILIO_VERIFY_SID", "")      # Verify "Service SID", starts with VA
FAST2SMS_API_KEY = os.getenv("FAST2SMS_API_KEY", "")
SMS_TIMEOUT_S = 20

OTP_TTL_MIN = 5            # a code works for 5 minutes
OTP_MAX_ATTEMPTS = 5       # then a new code must be requested
OTP_RESEND_S = 30          # minimum gap between code requests for one number
SESSION_HOURS = 12         # stay signed in for one working day
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"  # set true when served over https

# Phone push alerts for staff (ntfy: free app for Android/iOS). Each person installs the ntfy app
# and subscribes to their role's topic. Topic names act like passwords: make them long and random.
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC_GP = os.getenv("NTFY_TOPIC_GP", "")
NTFY_TOPIC_NGO = os.getenv("NTFY_TOPIC_NGO", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")   # link opened from a notification
ESCALATE_AFTER_MIN = float(os.getenv("ESCALATE_AFTER_MIN", "15"))  # re-alert if nobody acted for this long
ESCALATE_MAX_TIMES = int(os.getenv("ESCALATE_MAX_TIMES", "8"))     # stop after this many alerts per item
ESCALATION_CHECK_S = 60                                              # how often the server checks

EMERGENCY_NUMBER = "112"    # India's single emergency number (ERSS)
ALERT_LEVELS = ("HIGH",)    # levels that get an alert drafted automatically

# Origins allowed to call the API from a browser (your dashboard). Add your Vercel URL.
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


@lru_cache
def rule_config() -> dict:
    if not RULE_CONFIG.exists():
        raise RuntimeError(
            f"{RULE_CONFIG} is missing. Run: python ml/scripts/calibrate_rule.py"
        )
    return json.loads(RULE_CONFIG.read_text())
