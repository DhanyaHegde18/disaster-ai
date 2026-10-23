"""
Disaster AI backend.

Run from the project root:
    uvicorn backend.app.main:app --reload
Then open:
    http://localhost:8000/                    Gram Panchayat dashboard
    http://localhost:8000/docs                interactive API docs (try every endpoint here)
    http://localhost:8000/risk                current risk for all villages
    http://localhost:8000/alerts              drafted alerts and their review status
    http://localhost:8000/system/scheduler    when automatic scoring last ran and runs next
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, database
from .jobs import scheduler
from .routers import alerts, risk


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()  # create the alerts table on first run
    task = asyncio.create_task(scheduler.scheduler_loop()) if config.SCHEDULER_ENABLED else None
    yield
    if task:
        task.cancel()   # stop the scheduler cleanly when the server stops


app = FastAPI(
    title="Disaster AI: Flood & Landslide Early Warning",
    description="Village-level flood and landslide risk for Coastal and Malnad Karnataka, "
                "with AI-drafted bilingual alerts reviewed by the Gram Panchayat.",
    version="0.3.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(risk.router)
app.include_router(alerts.router)

# Gram Panchayat dashboard (plain HTML/JS in frontend/dashboard), served by this same server.
DASHBOARD_DIR = config.PROJECT_DIR / "frontend" / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard/" if DASHBOARD_DIR.exists() else "/docs")


@app.get("/health", tags=["system"])
def health():
    cfg = config.rule_config()
    return {"status": "ok", "engine": "rule-v1", "calibrated_on": cfg["calibrated_on"],
            "villages": len(cfg["villages"]),
            "alert_drafting": f"gemini ({config.GEMINI_MODEL})" if config.GEMINI_API_KEY else "template only (no GEMINI_API_KEY)",
            "automatic_scoring": f"every {config.SCORING_INTERVAL_MIN:g} min" if config.SCHEDULER_ENABLED else "off"}


@app.get("/system/scheduler", tags=["system"])
def scheduler_status():
    """When automatic scoring last ran, what it found, and when it runs next."""
    return scheduler.state


@app.post("/system/scheduler/run-now", tags=["system"])
async def scheduler_run_now():
    """Run one scoring + alert-drafting cycle immediately, without waiting for the timer."""
    if scheduler.state["running_now"]:
        return {"detail": "A cycle is already running; check /system/scheduler in a moment."}
    return await scheduler.run_once_tracked()
