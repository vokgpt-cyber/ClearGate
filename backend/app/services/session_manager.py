"""Session management for CLEARGATE with optional disk persistence.

Each session contains a NER pipeline and an EntityRegistry.
Sessions auto-expire after a configurable TTL.

When a SessionStore is provided, sessions are transparently
persisted to SQLite and can survive backend restarts.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock

import structlog

from app.services.entity_registry import EntityRegistry
from app.services.ner_pipeline import NERPipeline
from app.services.session_store import SessionStore

UTC = timezone.utc

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
        created_at: datetime | None = None,
    ) -> None:
        self.session_id = session_id
        self.locale = locale
        self.enable_llm_layer = enable_llm_layer
        self.custom_entities = custom_entities
        self.spacy_model = spacy_model or "ru_core_news_sm"
        self.created_at = created_at or datetime.now(UTC)
        self.pipeline = NERPipeline(
            spacy_model=self.spacy_model,
            gliner_model=None,
            enable_llm_layer=enable_llm_layer,
        )
        self.registry = EntityRegistry(
            master_key=master_key,
            session_id=session_id,
            locale=locale,
        )
        self.docx_bytes: bytes | None = None
        self.docx_filename: str | None = None
        self.response_docx_bytes: bytes | None = None
        self.response_docx_filename: str | None = None
        self.deanonymized_docx_bytes: bytes | None = None


class SessionManager:
    """Thread-safe session store with optional SQLite persistence.

    Implements singleton pattern -- use SessionManager.instance().
    """

    _instance: SessionManager | None = None
    _lock = Lock()

    def __init__(
        self,
        master_key: bytes | None = None,
        ttl_minutes: int = _DEFAULT_TTL_MINUTES,
        store: SessionStore | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._master_key = master_key or secrets.token_bytes(32)
        self._ttl_minutes = ttl_minutes
        self._store = store

    @classmethod
    def instance(
        cls,
        master_key: bytes | None = None,
        store: SessionStore | None = None,
    ) -> SessionManager:
        """Get or create the singleton SessionManager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(master_key=master_key, store=store)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    @property
    def store(self) -> SessionStore | None:
        return self._store

    def create_session(
        self,
        session_id: str | None = None,
        locale: str = "ru",
        enable_llm_layer: bool = False,
        custom_entities: list[str] | None = None,
        spacy_model: str | None = "ru_core_news_sm",
    ) -> Session:
        """Create a new anonymization session.

        If ``CLEARGATE_DISABLE_LLM_LAYER=true`` is set in the environment,
        the slow LLM verification layer is force-disabled here even when
        the caller asked for LLM verification. This lets IT turn off the
        slow CPU-bound layer on a pilot box without a code change.
        """
        # Late import to avoid a circular module-load order at startup.
        from app.config import settings

        if settings.cleargate_disable_llm_layer and enable_llm_layer:
            logger.info(
                "session.llm_layer_disabled_by_env",
                reason="CLEARGATE_DISABLE_LLM_LAYER=true",
            )
            enable_llm_layer = False

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
        self._persist(session)
        logger.info("session.created", session_id=session_id, locale=locale)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID, or None if not found or expired.

        If the session is not in RAM but exists on disk, it is
        hydrated from the persisted state.
        """
        session = self._sessions.get(session_id)
        if session is None and self._store is not None:
            session = self._hydrate_from_store(session_id)
        if session is None:
            return None
        if self._is_expired(session):
            self.close_session(session_id)
            return None
        return session

    def close_session(self, session_id: str) -> None:
        """Close session and securely clear all data (RAM + disk)."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.registry.clear()
            session.docx_bytes = None
            session.docx_filename = None
            session.response_docx_bytes = None
            session.response_docx_filename = None
            session.deanonymized_docx_bytes = None
        if self._store is not None:
            self._store.delete_session(session_id)
        logger.info("session.closed", session_id=session_id)

    def save_session(self, session_id: str) -> None:
        """Explicitly persist current state to disk.

        Called by routers after mutations (anonymize, upload, etc.).
        """
        session = self._sessions.get(session_id)
        if session is not None:
            self._persist(session)

    def list_sessions(self) -> list[dict]:
        """List all persisted sessions (metadata only, no blobs)."""
        if self._store is None:
            return [
                {
                    "session_id": s.session_id,
                    "locale": s.locale,
                    "created_at": s.created_at.isoformat(),
                    "entity_count": s.registry.entity_count,
                    "has_document": s.docx_bytes is not None,
                    "docx_filename": s.docx_filename,
                }
                for s in self._sessions.values()
                if not self._is_expired(s)
            ]
        rows = self._store.list_sessions()
        result = []
        for row in rows:
            mem_session = self._sessions.get(row["session_id"])
            custom = json.loads(row.get("custom_entities", "[]"))
            result.append({
                "session_id": row["session_id"],
                "locale": row["locale"],
                "created_at": row["created_at"],
                "entity_count": (
                    mem_session.registry.entity_count if mem_session else 0
                ),
                "has_document": row.get("docx_filename") is not None,
                "docx_filename": row.get("docx_filename"),
                "custom_entities": custom,
                "updated_at": row.get("updated_at"),
            })
        return result

    # -- Internal -----------------------------------------------------

    def _persist(self, session: Session) -> None:
        """Save session state to disk if a store is attached."""
        if self._store is None:
            return
        try:
            registry_blob = session.registry.export_encrypted()
        except Exception:
            logger.warning(
                "session.persist_registry_failed",
                session_id=session.session_id,
            )
            registry_blob = None
        self._store.save_session(
            session_id=session.session_id,
            locale=session.locale,
            created_at=session.created_at,
            custom_entities=session.custom_entities,
            enable_llm_layer=session.enable_llm_layer,
            spacy_model=session.spacy_model,
            registry_blob=registry_blob,
            docx_bytes=session.docx_bytes,
            docx_filename=session.docx_filename,
            response_docx_bytes=session.response_docx_bytes,
            response_docx_filename=getattr(
                session, "response_docx_filename", None
            ),
            deanonymized_docx_bytes=session.deanonymized_docx_bytes,
        )

    def _hydrate_from_store(self, session_id: str) -> Session | None:
        """Restore a session from disk into RAM."""
        if self._store is None:
            return None
        data = self._store.load_session(session_id)
        if data is None:
            return None
        created_at = datetime.fromisoformat(data["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        custom_entities = json.loads(data.get("custom_entities", "[]"))
        session = Session(
            session_id=session_id,
            locale=data["locale"],
            enable_llm_layer=bool(data.get("enable_llm_layer", 0)),
            custom_entities=custom_entities,
            master_key=self._master_key,
            spacy_model=data.get("spacy_model", "ru_core_news_sm"),
            created_at=created_at,
        )
        registry_blob = data.get("registry_blob")
        if registry_blob is not None:
            try:
                session.registry.import_encrypted(registry_blob)
                logger.info(
                    "session.hydrated_registry",
                    session_id=session_id,
                    entity_count=session.registry.entity_count,
                )
            except Exception:
                logger.warning(
                    "session.hydrate_registry_failed",
                    session_id=session_id,
                )
        session.docx_bytes = data.get("docx_bytes")
        session.docx_filename = data.get("docx_filename")
        session.response_docx_bytes = data.get("response_docx_bytes")
        session.response_docx_filename = data.get("response_docx_filename")
        session.deanonymized_docx_bytes = data.get("deanonymized_docx_bytes")
        self._sessions[session_id] = session
        logger.info("session.hydrated", session_id=session_id)
        return session

    def _is_expired(self, session: Session) -> bool:
        """Check if session has exceeded its TTL."""
        ttl = timedelta(minutes=self._ttl_minutes)
        return datetime.now(UTC) - session.created_at > ttl
