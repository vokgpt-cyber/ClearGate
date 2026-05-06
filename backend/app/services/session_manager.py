"""Session management for CLEARGATE with optional disk persistence.

Each session contains a NER pipeline and an EntityRegistry.
Sessions auto-expire after a configurable TTL.

When a SessionStore is provided, sessions are transparently
persisted to SQLite and can survive backend restarts.

Sprint B.3: every session is owned by a user.  All public accessor
methods require a ``user_id`` and return/mutate only sessions the
caller owns.  Cross-user access returns the same "session not found"
answer as a missing session, so nothing leaks about the existence of
other users' data.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock

import structlog

from app.services.entity_registry import EntityRegistry
from app.services.ner_pipeline import ChunkCache, NERPipeline
from app.services.session_store import SessionStore
from app.models.entities import DetectedEntity

UTC = timezone.utc

logger = structlog.get_logger(__name__)

_DEFAULT_TTL_MINUTES = 1440  # 24 hours
_LEGACY_USER_ID = "__local__"


class Session:
    """A single anonymization session with its own pipeline and registry."""

    def __init__(
        self,
        session_id: str,
        locale: str,
        enable_llm_layer: bool,
        custom_entities: list[str],
        master_key: bytes,
        user_id: str,
        spacy_model: str | None = None,
        source_format: str | None = None,
        source_filename: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        from app.config import settings

        self.session_id = session_id
        self.user_id = user_id
        self.locale = locale
        self.enable_llm_layer = enable_llm_layer
        self.custom_entities = custom_entities
        self.spacy_model = spacy_model or settings.spacy_model
        self.source_format = source_format
        self.source_filename = source_filename
        self.created_at = created_at or datetime.now(UTC)
        self.pipeline = NERPipeline(
            spacy_model=self.spacy_model,
            gliner_model=settings.gliner_model,
            ollama_model=settings.ollama_model,
            enable_llm_layer=enable_llm_layer,
            default_gliner_labels=settings.default_gliner_labels_list,
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
        self.deanonymize_result_json: str | None = None
        self.manual_resolutions_json: str | None = None
        self.workflow_stage: str = "anonymized"
        self.anonymized_text: str | None = None
        self.detected_entities: list[DetectedEntity] = []
        # v0.4.0 Phase 2: cache chunks + embeddings across /anonymize calls
        self.chunk_cache: ChunkCache | None = None


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

    # ------------------------------------------------------------------
    # Public API -- every method is scoped to a user_id.
    # ------------------------------------------------------------------

    def create_session(
        self,
        user_id: str = _LEGACY_USER_ID,
        session_id: str | None = None,
        locale: str = "ru",
        enable_llm_layer: bool = True,
        custom_entities: list[str] | None = None,
        spacy_model: str | None = None,
    ) -> Session:
        """Create a new anonymization session owned by ``user_id``."""
        from app.config import settings

        if not user_id:
            raise ValueError("create_session requires a non-empty user_id")

        if session_id is None:
            session_id = secrets.token_urlsafe(16)
        effective_llm_layer = enable_llm_layer and not settings.cleargate_disable_llm_layer
        session = Session(
            session_id=session_id,
            user_id=user_id,
            locale=locale,
            enable_llm_layer=effective_llm_layer,
            custom_entities=custom_entities or [],
            master_key=self._master_key,
            spacy_model=spacy_model,
            source_format=None,
            source_filename=None,
        )
        self._sessions[session_id] = session
        self._persist(session)
        logger.info(
            "session.created",
            session_id=session_id, user_id=user_id, locale=locale,
            deep_scan_enabled=effective_llm_layer,
        )
        return session

    def get_session(
        self, session_id: str, user_id: str = _LEGACY_USER_ID
    ) -> Session | None:
        """Get session by ID scoped to ``user_id``.

        Returns None if:
          * the session does not exist, or
          * it has expired, or
          * it is owned by a different user.

        If the session is not in RAM but a matching row exists on disk
        for this user, it is hydrated.
        """
        if not user_id:
            return None
        session = self._sessions.get(session_id)
        if session is not None and session.user_id != user_id:
            # Somebody else's live session -- pretend it does not exist.
            return None
        if session is None and self._store is not None:
            session = self._hydrate_from_store(session_id, user_id)
        if session is None:
            return None
        if self._is_expired(session):
            self.close_session(session_id, user_id)
            return None
        return session

    def close_session(
        self, session_id: str, user_id: str = _LEGACY_USER_ID
    ) -> None:
        """Close session and securely clear all data (RAM + disk).

        Only closes the session if it is owned by ``user_id``.  Calls
        for somebody else's session are a silent no-op so nothing leaks.
        """
        if not user_id:
            return
        session = self._sessions.get(session_id)
        if session is not None and session.user_id != user_id:
            return
        session = self._sessions.pop(session_id, None)
        if session:
            session.registry.clear()
            session.docx_bytes = None
            session.docx_filename = None
            session.source_format = None
            session.source_filename = None
            session.response_docx_bytes = None
            session.response_docx_filename = None
            session.deanonymized_docx_bytes = None
            session.deanonymize_result_json = None
            session.manual_resolutions_json = None
            session.workflow_stage = "anonymized"
            session.anonymized_text = None
            session.detected_entities.clear()
        if self._store is not None:
            self._store.delete_session(session_id, user_id=user_id)
        logger.info("session.closed", session_id=session_id, user_id=user_id)

    def close_sessions_for_user(self, user_id: str) -> int:
        """Close and delete every session owned by ``user_id``."""
        if not user_id:
            return 0
        closed = 0
        for session_id, session in list(self._sessions.items()):
            if session.user_id != user_id:
                continue
            session.registry.clear()
            session.docx_bytes = None
            session.docx_filename = None
            session.source_format = None
            session.source_filename = None
            session.response_docx_bytes = None
            session.response_docx_filename = None
            session.deanonymized_docx_bytes = None
            session.deanonymize_result_json = None
            session.manual_resolutions_json = None
            session.workflow_stage = "anonymized"
            session.detected_entities.clear()
            self._sessions.pop(session_id, None)
            closed += 1
        if self._store is not None:
            closed = max(closed, self._store.delete_sessions_for_user(user_id))
        logger.info("session.closed_for_user", user_id=user_id, count=closed)
        return closed

    def save_session(
        self, session_id: str, user_id: str = _LEGACY_USER_ID
    ) -> None:
        """Explicitly persist current state to disk.

        Called by routers after mutations (anonymize, upload, etc.).
        No-op if the session is not owned by ``user_id``.
        """
        session = self._sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return
        self._persist(session)

    def list_sessions(self, user_id: str = _LEGACY_USER_ID) -> list[dict]:
        """List persisted sessions for ``user_id`` (metadata only, no blobs)."""
        if not user_id:
            return []
        if self._store is None:
            return [
                {
                    "session_id": s.session_id,
                    "locale": s.locale,
                    "created_at": s.created_at.isoformat(),
                    "entity_count": s.registry.entity_count,
                    "has_document": s.docx_bytes is not None,
                    "docx_filename": s.source_filename or s.docx_filename,
                    "source_format": s.source_format,
                    "source_filename": s.source_filename,
                    "workflow_stage": getattr(s, "workflow_stage", "anonymized"),
                    "has_response": s.response_docx_bytes is not None,
                    "has_deanonymized": s.deanonymized_docx_bytes is not None,
                    "has_anonymization": bool(
                        s.anonymized_text and s.detected_entities
                    ),
                }
                for s in self._sessions.values()
                if s.user_id == user_id and not self._is_expired(s)
            ]
        rows = self._store.list_sessions(user_id=user_id)
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
                "docx_filename": row.get("source_filename") or row.get("docx_filename"),
                "source_format": row.get("source_format"),
                "source_filename": row.get("source_filename"),
                "workflow_stage": row.get("workflow_stage") or "anonymized",
                "has_response": bool(row.get("has_response")),
                "has_deanonymized": bool(row.get("has_deanonymized")),
                "has_anonymization": bool(
                    row.get("anonymized_text") and row.get("entities_json")
                ),
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
            user_id=session.user_id,
            locale=session.locale,
            created_at=session.created_at,
            custom_entities=session.custom_entities,
            enable_llm_layer=session.enable_llm_layer,
            spacy_model=session.spacy_model,
            source_format=session.source_format,
            source_filename=session.source_filename,
            registry_blob=registry_blob,
            docx_bytes=session.docx_bytes,
            docx_filename=session.docx_filename,
            response_docx_bytes=session.response_docx_bytes,
            response_docx_filename=getattr(
                session, "response_docx_filename", None
            ),
            deanonymized_docx_bytes=session.deanonymized_docx_bytes,
            deanonymize_result_json=getattr(
                session, "deanonymize_result_json", None
            ),
            manual_resolutions_json=getattr(
                session, "manual_resolutions_json", None
            ),
            workflow_stage=getattr(session, "workflow_stage", "anonymized"),
            anonymized_text=session.anonymized_text,
            entities_json=json.dumps(
                [e.model_dump() for e in session.detected_entities],
                ensure_ascii=False,
            ) if session.detected_entities else None,
        )

    def _hydrate_from_store(self, session_id: str, user_id: str) -> Session | None:
        """Restore a session from disk into RAM, scoped to ``user_id``."""
        from app.config import settings

        if self._store is None:
            return None
        data = self._store.load_session(session_id, user_id=user_id)
        if data is None:
            return None
        created_at = datetime.fromisoformat(data["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        custom_entities = json.loads(data.get("custom_entities", "[]"))
        # Fallback is defence in depth: the store already filtered by
        # user_id, but if the row predates Sprint B.3 and happens to
        # match the session_id, we still require a user_id to hydrate.
        session = Session(
            session_id=session_id,
            user_id=data.get("user_id") or user_id,
            locale=data["locale"],
            enable_llm_layer=(
                bool(data.get("enable_llm_layer", 0))
                and not settings.cleargate_disable_llm_layer
            ),
            custom_entities=custom_entities,
            master_key=self._master_key,
            spacy_model=None,
            source_format=data.get("source_format"),
            source_filename=data.get("source_filename"),
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
        session.deanonymize_result_json = data.get("deanonymize_result_json")
        session.manual_resolutions_json = data.get("manual_resolutions_json")
        session.workflow_stage = data.get("workflow_stage") or "anonymized"
        session.anonymized_text = data.get("anonymized_text")
        entities_json = data.get("entities_json")
        if entities_json:
            try:
                raw_entities = json.loads(entities_json)
                session.detected_entities = [
                    DetectedEntity(**item) for item in raw_entities
                ]
            except Exception:
                logger.warning(
                    "session.hydrate_entities_failed",
                    session_id=session_id,
                    exc_info=True,
                )
        self._sessions[session_id] = session
        logger.info("session.hydrated", session_id=session_id, user_id=user_id)
        return session

    def _is_expired(self, session: Session) -> bool:
        """Check if session has exceeded its TTL."""
        ttl = timedelta(minutes=self._ttl_minutes)
        return datetime.now(UTC) - session.created_at > ttl
