"""
Disaster AI backend.

Run from the project root:
    uvicorn backend.app.main:app --reload
Then open:
    http://localhost:8000/                    Gram Panchayat dashboard
    http://localhost:8000/villager/           villagers' warning page (approved alerts only)
    http://localhost:8000/docs                interactive API docs (try every endpoint here)
    http://localhost:8000/risk                current risk for all villages
    http://localhost:8000/alerts              drafted alerts and their review status
    http://localhost:8000/system/scheduler    when automatic scoring last ran and runs next
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import areas, config, database
from .auth import require_gp, require_official
from .jobs import escalation, scheduler
from . import notify
from .routers import alerts, auth, public, relief, risk, shelters, villagers
from .services import shelters as shelter_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()  # create the tables on first run
    areas.get()                    # load the ~28,000 villages once
    shelter_data.sync_from_csv()   # relief centres + OpenStreetMap candidates (only if the files changed)
    tasks = []
    if config.SCHEDULER_ENABLED:
        tasks.append(asyncio.create_task(scheduler.scheduler_loop()))
    if notify.topics_for(("gp", "ngo")):          # phone reminders only if ntfy topics are set
        tasks.append(asyncio.create_task(escalation.escalation_loop()))
    yield
    for t in tasks:
        t.cancel()      # stop background jobs cleanly when the server stops


app = FastAPI(
    title="Disaster AI: Flood & Landslide Early Warning",
    description="Flood and landslide risk for all of Karnataka on IMD's rain grid, "
                "with AI-drafted bilingual alerts per taluk reviewed by the Gram Panchayat.",
    version="0.7.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
# Open to everyone: /health, /public/status + /public/villages (warnings), sign-in endpoints, the two pages.
# Villager session: /public/me, /public/report.  Staff session (GP or NGO): /risk, /alerts (NGO: approved only),
# /relief/summary, /shelters.  Gram Panchayat only: drafting/reviewing alerts, /relief/reports,
# opening/closing relief centres (PATCH /shelters), running checks.  Open: /public/shelters (nearest centres).
app.include_router(auth.router)
app.include_router(risk.router)
app.include_router(alerts.router)
app.include_router(public.router)
app.include_router(villagers.router)
app.include_router(relief.router)
app.include_router(shelters.router)
app.include_router(shelters.public_router)

# Pages served by this same server (plain HTML/JS, no build step):
#   /dashboard/  Gram Panchayat control centre    /villager/  villagers' warning page
DASHBOARD_DIR = config.PROJECT_DIR / "frontend" / "dashboard"
VILLAGER_DIR = config.PROJECT_DIR / "frontend" / "villager"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
if VILLAGER_DIR.exists():
    app.mount("/villager", StaticFiles(directory=VILLAGER_DIR, html=True), name="villager")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard/" if DASHBOARD_DIR.exists() else "/docs")


@app.get("/health", tags=["system"])
def health():
    grid = config.grid_config()
    a = areas.get()
    return {"status": "ok", "engine": "rule-v2-grid",
            "thresholds": ("DEMO placeholders: run ml/scripts/build_grid.py" if grid["demo"]
                           else f"from {grid.get('source', 'IMD')}, calibrated {grid.get('calibrated_on')}"),
            "coverage": f"{len(a.villages)} villages, {len(a.taluks)} taluks, {len(a.districts)} districts, "
                        f"{len(grid['cells'])} rain-grid squares",
            "alert_drafting": f"gemini ({config.GEMINI_MODEL})" if config.GEMINI_API_KEY else "template only (no GEMINI_API_KEY)",
            "automatic_scoring": f"every {config.SCORING_INTERVAL_MIN:g} min" if config.SCHEDULER_ENABLED else "off",
            "sign_in": "demo codes on screen" if config.OTP_DEMO_MODE else f"SMS codes via {config.SMS_PROVIDER}",
            "public_address": notify.public_url() + ("" if config.PUBLIC_URL else " (learned from the dashboard)"),
            "phone_alerts": (f"ntfy, a topic per taluk (GP) and district (NGO), reminders every "
                             f"{config.ESCALATE_AFTER_MIN:g} min") if notify.topics_for(("gp", "ngo"))
                            else "off (set NTFY_TOPIC_GP / NTFY_TOPIC_NGO)"}


@app.get("/system/scheduler", tags=["system"], dependencies=[Depends(require_official)])
def scheduler_status():
    """When automatic scoring last ran, what it found, and when it runs next."""
    return scheduler.state


@app.post("/system/scheduler/run-now", tags=["system"], dependencies=[Depends(require_gp)])
async def scheduler_run_now():
    """Run one scoring + alert-drafting cycle immediately, without waiting for the timer."""
    if scheduler.state["running_now"]:
        return {"detail": "A cycle is already running; check /system/scheduler in a moment."}
    return await scheduler.run_once_tracked()
