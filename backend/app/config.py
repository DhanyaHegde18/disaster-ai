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
