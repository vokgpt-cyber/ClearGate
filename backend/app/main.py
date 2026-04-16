"""CLEARGATE Backend — FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import anonymize, documents, health, llm_ws, sessions
from app.services.session_store import SessionStore
from app.services.session_manager import SessionManager

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    # Initialize session persistence
    store_dir = Path(settings.session_store_dir)
    if not store_dir.is_absolute():
        # Resolve relative to backend/ directory
        store_dir = Path(__file__).resolve().parent.parent / store_dir
    db_path = store_dir / "sessions.db"
    store = SessionStore(db_path=db_path, ttl_minutes=settings.session_ttl_minutes)
    store.prune_expired()

    # Initialize SessionManager singleton with persistence
    SessionManager.reset()  # ensure clean state on reload
    sm = SessionManager.instance(store=store)

    logger.info(
        "app.startup",
        profile=settings.cleargate_profile,
        version=settings.version,
        host=settings.backend_host,
        port=settings.backend_port,
        session_store=str(db_path),
    )
    yield
    # Shutdown: close store
    if sm.store is not None:
        sm.store.close()
    SessionManager.reset()
    logger.info("app.shutdown")


app = FastAPI(
    title="CLEARGATE Backend",
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
    # Expose Content-Disposition so the frontend can read the filename
    # from export responses (CORS hides it by default).
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(anonymize.router)
app.include_router(llm_ws.router)
