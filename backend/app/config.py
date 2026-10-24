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

GRID_CONFIG = APP_DIR / "grid_config.json"          # written by ml/scripts/build_grid.py (your IMD data)
GRID_CONFIG_DEMO = APP_DIR / "grid_config.demo.json"  # placeholder thresholds, used until you run build_grid.py
VILLAGES_CSV = PROJECT_DIR / "ml" / "data" / "karnataka_villages.csv"   # ml/scripts/build_villages.py
AREAS_JSON = PROJECT_DIR / "ml" / "data" / "karnataka_areas.json"
SHELTER_CANDIDATES_CSV = PROJECT_DIR / "ml" / "data" / "shelter_candidates.csv"  # ml/scripts/fetch_osm_buildings.py
LATEST_RISK_FILE = BACKEND_DIR / "data" / "latest_risk.json"
ALERTS_DB = BACKEND_DIR / "data" / "alerts.db"
SHELTERS_CSV = PROJECT_DIR / "ml" / "data" / "shelters.csv"   # relief centres; edit this file to add real ones

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
SESSION_HOURS = 12         # staff stay signed in for one working day
VILLAGER_SESSION_DAYS = 30  # villagers stay signed in a month, so a report saved offline can still be sent later
# Session cookies are made https-only automatically when the page came over https; true forces it always.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Phone push alerts for staff (ntfy: free app for Android/iOS). Each person installs the ntfy app
# and subscribes to their role's topic. Topic names act like passwords: make them long and random.
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC_GP = os.getenv("NTFY_TOPIC_GP", "")
NTFY_TOPIC_NGO = os.getenv("NTFY_TOPIC_NGO", "")
# Link opened from a phone notification. Normally leave it unset: the app learns its public address
# (tunnel, Tailscale, Wi-Fi IP) from the dashboard itself. Set it only to force a particular address.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ESCALATE_AFTER_MIN = float(os.getenv("ESCALATE_AFTER_MIN", "15"))  # re-alert if nobody acted for this long
ESCALATE_MAX_TIMES = int(os.getenv("ESCALATE_MAX_TIMES", "8"))     # stop after this many alerts per item
ESCALATION_CHECK_S = 60                                              # how often the server checks

EMERGENCY_NUMBER = "112"    # India's single emergency number (ERSS)
ALERT_LEVELS = ("HIGH",)    # levels that get an alert drafted automatically

# Origins allowed to call the API from a browser (your dashboard). Add your Vercel URL.
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


FORECAST_BATCH = 100        # grid squares per Open-Meteo request
FORECAST_PAUSE_S = 2        # pause between those requests


@lru_cache
def grid_config() -> dict:
    """Thresholds per rain-grid square. Falls back to the demo file (marked demo=True) until
    ml/scripts/build_grid.py has been run on your IMD data."""
    path = GRID_CONFIG if GRID_CONFIG.exists() else GRID_CONFIG_DEMO
    if not path.exists():
        raise RuntimeError(f"{GRID_CONFIG} is missing. Run: python ml/scripts/build_grid.py")
    cfg = json.loads(path.read_text())
    cfg["demo"] = path == GRID_CONFIG_DEMO or cfg.get("demo", False)
    return cfg
