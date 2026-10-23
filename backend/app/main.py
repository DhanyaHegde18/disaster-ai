"""
Disaster AI backend.

Run from the project root:
    uvicorn backend.app.main:app --reload
Then open:
    http://localhost:8000/docs     interactive API docs (try every endpoint here)
    http://localhost:8000/risk     current risk for all villages
    http://localhost:8000/alerts   drafted alerts and their review status
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, database
from .routers import alerts, risk


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()  # create the alerts table on first run
    yield


app = FastAPI(
    title="Disaster AI: Flood & Landslide Early Warning",
    description="Village-level flood and landslide risk for Coastal and Malnad Karnataka, "
                "with AI-drafted bilingual alerts reviewed by the Gram Panchayat.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(risk.router)
app.include_router(alerts.router)


@app.get("/health", tags=["system"])
def health():
    cfg = config.rule_config()
    return {"status": "ok", "engine": "rule-v1", "calibrated_on": cfg["calibrated_on"],
            "villages": len(cfg["villages"]),
            "alert_drafting": f"gemini ({config.GEMINI_MODEL})" if config.GEMINI_API_KEY else "template only (no GEMINI_API_KEY)"}
