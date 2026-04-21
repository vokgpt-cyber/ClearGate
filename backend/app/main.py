"""CLEARGATE Backend — FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import anonymize, auth as auth_router, documents, health, llm_ws, sessions
from app.services.auth import init_auth_service, resolve_signing_secret
from app.services.session_store import SessionStore
from app.services.session_manager import SessionManager
from app.services.user_store import UserStore

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

    # Sprint B.2 -- local user accounts + auth service
    users_db_path = store_dir / "users.db"
    user_store = UserStore(db_path=users_db_path)
    signing_secret = resolve_signing_secret(
        configured=settings.cleargate_session_cookie_secret,
        secret_file_path=store_dir / "session_cookie.key",
    )
    init_auth_service(
        signing_secret=signing_secret,
        max_age_seconds=settings.cleargate_auth_session_ttl_minutes * 60,
    )

    # Wire the UserStore dependency into the auth router without
    # leaking it into module-level state (keeps tests tractable).
    app.dependency_overrides[auth_router.get_user_store_from_request] = lambda: user_store

    logger.info(
        "app.startup",
        profile=settings.cleargate_profile,
        version=settings.version,
        host=settings.backend_host,
        port=settings.backend_port,
        session_store=str(db_path),
        user_store=str(users_db_path),
        user_count=user_store.count(),
        auth_session_ttl_min=settings.cleargate_auth_session_ttl_minutes,
        # Surfaced for IT diagnosability — these three values are the
        # most common source of "LLM verification not working" tickets,
        # so they go into the very first log line on boot.
        ollama_host=settings.ollama_host,
        ollama_model=settings.ollama_model,
        llm_layer_disabled=settings.cleargate_disable_llm_layer,
    )
    yield
    # Shutdown: close stores
    if sm.store is not None:
        sm.store.close()
    user_store.close()
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
app.include_router(auth_router.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(anonymize.router)
app.include_router(llm_ws.router)
