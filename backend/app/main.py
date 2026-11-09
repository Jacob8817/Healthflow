from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from app.ai.forecasting.model_loader import ForecastModelLoader
from app.ai.forecasting.service import ForecastService
from app.api.router import router
from app.api.operations import router as operations_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import User
from app.db.session import SessionLocal, engine
from app.services.intelligence import OperationsIntelligenceService
from app.services.optimisation import OptimisationService
from app.services.simulation import SimulationService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == settings.demo_admin_email))
        if settings.seed_demo_admin and not admin:
            db.add(User(
                email=settings.demo_admin_email, full_name="HealthFlow Administrator",
                password_hash=hash_password(settings.demo_admin_password), role="admin",
            ))
            db.commit()
    loader = ForecastModelLoader(settings.forecast_model_dir, settings.forecast_model_file)
    try:
        loader.load()
    except Exception:
        pass
    app.state.model_loader = loader
    app.state.forecast_service = ForecastService(loader)
    app.state.simulation_service = SimulationService()
    app.state.optimisation_service = OptimisationService()
    app.state.intelligence_service = OperationsIntelligenceService(settings)
    yield


app = FastAPI(
    title="HealthFlow API",
    description="Aggregate NHS emergency-demand forecasting and operational planning.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(operations_router, prefix=settings.api_v1_prefix)


@app.get("/health/live")
def live():
    return {"status": "healthy"}


@app.get("/health/ready")
def ready():
    state = app.state.model_loader.status()
    if state["state"] != "loaded":
        return Response(
            content='{"status":"degraded","component":"forecast_model"}',
            media_type="application/json", status_code=503,
        )
    return {"status": "ready", "model": state}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
