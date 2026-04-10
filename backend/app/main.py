"""VELUM Backend — FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import anonymize, debug, documents, health, llm_ws, sessions

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    logger.info(
        "app.startup",
        profile=settings.velum_profile,
        version=settings.version,
        host=settings.backend_host,
        port=settings.backend_port,
    )
    yield
    logger.info("app.shutdown")


app = FastAPI(
    title="VELUM Backend",
    description="On-premise anonymization gateway for legal AI workflows",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(anonymize.router)
app.include_router(llm_ws.router)
app.include_router(debug.router)
