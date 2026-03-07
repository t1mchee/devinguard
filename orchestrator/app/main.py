"""DevinGuard Orchestrator — FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.dashboard import router as dashboard_router
from app.api.webhooks import router as webhooks_router
from app.metrics.store import MetricsStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and clean up application resources."""
    # Initialize metrics store
    metrics_store = MetricsStore()
    await metrics_store.initialize()
    app.state.metrics_store = metrics_store
    yield
    # Cleanup
    await metrics_store.close()


app = FastAPI(
    title="DevinGuard",
    description="Autonomous Incident Response — From Alert to Fix PR",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins for demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(webhooks_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api/dashboard")

# Serve dashboard static files
app.mount("/dashboard", StaticFiles(directory="app/dashboard", html=True), name="dashboard")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "devinguard"}
