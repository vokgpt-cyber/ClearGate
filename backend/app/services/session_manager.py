"""In-memory session management for VELUM.

Each session contains a NER pipeline and an EntityRegistry.
Sessions auto-expire after a configurable TTL.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from threading import Lock

import structlog

from app.services.entity_registry import EntityRegistry
from app.services.ner_pipeline import NERPipeline

logger = structlog.get_logger(__name__)

_DEFAULT_TTL_MINUTES = 1440  # 24 hours


class Session:
    """A single anonymization session with its own pipeline and registry."""

    def __init__(
        self,
        session_id: str,
        locale: str,
        enable_llm_layer: bool,
        custom_entities: list[str],
        master_key: bytes,
        spacy_model: str | None = "ru_core_news_sm",
    ) -> None:
        self.session_id = session_id
        self.locale = locale
        self.custom_entities = custom_entities
        self.created_at = datetime.now(UTC)
        self.pipeline = NERPipeline(
            spacy_model=spacy_model,
            gliner_model=None,  # GLiNER loaded on demand
            enable_llm_layer=enable_llm_layer,
        )
        self.registry = EntityRegistry(
            master_key=master_key,
            session_id=session_id,
            locale=locale,
        )


class SessionManager:
    """Thread-safe in-memory session store.

    Implements singleton pattern — use SessionManager.instance().
    """

    _instance: SessionManager | None = None
    _lock = Lock()

    def __init__(
        self,
        master_key: bytes | None = None,
        ttl_minutes: int = _DEFAULT_TTL_MINUTES,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._master_key = master_key or secrets.token_bytes(32)
        self._ttl_minutes = ttl_minutes

    @classmethod
    def instance(cls, master_key: bytes | None = None) -> SessionManager:
        """Get or create the singleton SessionManager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(master_key=master_key)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def create_session(
        self,
        session_id: str | None = None,
        locale: str = "ru",
        enable_llm_layer: bool = False,
        custom_entities: list[str] | None = None,
        spacy_model: str | None = "ru_core_news_sm",
    ) -> Session:
        """Create a new anonymization session."""
        if session_id is None:
            session_id = secrets.token_urlsafe(16)

        session = Session(
            session_id=session_id,
            locale=locale,
            enable_llm_layer=enable_llm_layer,
            custom_entities=custom_entities or [],
            master_key=self._master_key,
            spacy_model=spacy_model,
        )
        self._sessions[session_id] = session

        logger.info("session.created", session_id=session_id, locale=locale)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID, or None if not found or expired."""
        session = self._sessions.get(session_id)
        if session and self._is_expired(session):
            self.close_session(session_id)
            return None
        return session

    def close_session(self, session_id: str) -> None:
        """Close session and securely clear all data."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.registry.clear()
            logger.info("session.closed", session_id=session_id)

    def _is_expired(self, session: Session) -> bool:
        """Check if session has exceeded its TTL."""
        ttl = timedelta(minutes=self._ttl_minutes)
        return datetime.now(UTC) - session.created_at > ttl
