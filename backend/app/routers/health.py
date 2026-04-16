"""Health check endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response model for the health endpoint."""

    status: str
    version: str
    profile: str
    timestamp: str


class ReadinessCheck(BaseModel):
    """Individual readiness check result."""

    models_loaded: bool = False
    ollama_available: bool = False


class ReadinessResponse(BaseModel):
    """Response model for the readiness endpoint."""

    ready: bool
    checks: ReadinessCheck


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return current service health status."""
    return HealthResponse(
        status="ok",
        version=settings.version,
        profile=settings.cleargate_profile,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    """Check if all required services and models are loaded.

    Stub implementation — will be extended as services are added.
    """
    checks = ReadinessCheck(models_loaded=False, ollama_available=False)
    return ReadinessResponse(
        ready=checks.models_loaded and checks.ollama_available,
        checks=checks,
    )
