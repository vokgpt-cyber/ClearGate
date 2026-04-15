"""Tests for SessionManager + SessionStore integration.

Verifies that sessions survive simulated "restarts" (clearing
the in-memory session dict and rehydrating from SQLite).

NERPipeline and its heavy deps are mocked at the module level
because they require presidio/spaCy/GLiNER.
"""

import secrets
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# -- Mock heavy ML deps BEFORE importing session_manager ------------------
_mock_ner = MagicMock()
_mock_ner.NERPipeline = MagicMock
sys.modules.setdefault("presidio_analyzer", MagicMock())
sys.modules.setdefault("presidio_analyzer.nlp_engine", MagicMock())
sys.modules.setdefault("spacy", MagicMock())
sys.modules.setdefault("gliner", MagicMock())
if "app.services.ner_pipeline" not in sys.modules:
    sys.modules["app.services.ner_pipeline"] = _mock_ner

from app.services.session_manager import SessionManager  # noqa: E402
from app.services.session_store import SessionStore  # noqa: E402
from app.models.entities import DetectedEntity  # noqa: E402


@pytest.fixture()
def master_key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    s = SessionStore(db_path=tmp_path / "test.db", ttl_minutes=1440)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_singleton():
    SessionManager.reset()
    yield
    SessionManager.reset()


def _entity(text: str, entity_type: str = "PER", start: int = 0):
    return DetectedEntity(
        text=text,
        entity_type=entity_type,
        start=start,
        end=start + len(text),
        score=0.9,
    )


class TestPersistAndRestore:
    """Core persistence: create -> populate -> restart -> verify."""

    def test_session_survives_memory_clear(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        session = sm.create_session(locale="ru")
        sid = session.session_id

        session.registry.get_or_create_placeholder(_entity("Ivanov"))
        session.registry.get_or_create_placeholder(_entity("Gazprom", "ORG"))
        sm.save_session(sid)

        sm._sessions.clear()
        assert sm._sessions.get(sid) is None

        restored = sm.get_session(sid)
        assert restored is not None
        assert restored.session_id == sid
        assert restored.locale == "ru"
        assert restored.registry.entity_count == 2

    def test_registry_placeholders_consistent_after_restore(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        session = sm.create_session(locale="en")
        sid = session.session_id

        p1 = session.registry.get_or_create_placeholder(_entity("Smith"))
        p2 = session.registry.get_or_create_placeholder(_entity("Jones"))
        sm.save_session(sid)

        sm._sessions.clear()
        restored = sm.get_session(sid)

        assert restored.registry.deanonymize_text(p1) != p1
        assert restored.registry.deanonymize_text(p2) != p2
        text = f"Signed by {p1} and {p2}"
        deanon = restored.registry.deanonymize_text(text)
        assert "[PERSON_" not in deanon

    def test_docx_bytes_survive_restart(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        session = sm.create_session()
        sid = session.session_id
        session.docx_bytes = b"original-docx"
        session.docx_filename = "contract.docx"
        session.response_docx_bytes = b"response-docx"
        session.deanonymized_docx_bytes = b"deanonymized-docx"
        sm.save_session(sid)

        sm._sessions.clear()
        restored = sm.get_session(sid)
        assert restored.docx_bytes == b"original-docx"
        assert restored.docx_filename == "contract.docx"
        assert restored.response_docx_bytes == b"response-docx"
        assert restored.deanonymized_docx_bytes == b"deanonymized-docx"

    def test_close_removes_from_disk(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        session = sm.create_session()
        sid = session.session_id
        sm.save_session(sid)
        assert store.load_session(sid) is not None

        sm.close_session(sid)
        assert store.load_session(sid) is None
        assert sm.get_session(sid) is None

    def test_custom_entities_survive(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        session = sm.create_session(
            locale="ru", custom_entities=["DISTANCE", "HOURS"]
        )
        sid = session.session_id

        sm._sessions.clear()
        restored = sm.get_session(sid)
        assert restored.custom_entities == ["DISTANCE", "HOURS"]


class TestListSessions:
    """List sessions from persistence."""

    def test_list_includes_persisted(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        s1 = sm.create_session(locale="ru")
        s2 = sm.create_session(locale="en")
        sessions = sm.list_sessions()
        ids = [s["session_id"] for s in sessions]
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_list_after_restart(
        self, master_key: bytes, store: SessionStore,
    ) -> None:
        sm = SessionManager(master_key=master_key, store=store)
        s1 = sm.create_session()
        sm._sessions.clear()
        sessions = sm.list_sessions()
        ids = [s["session_id"] for s in sessions]
        assert s1.session_id in ids


class TestWithoutStore:
    """SessionManager works fine without a store (backward compat)."""

    def test_no_store_in_memory_only(self, master_key: bytes) -> None:
        sm = SessionManager(master_key=master_key, store=None)
        session = sm.create_session(locale="ru")
        sid = session.session_id
        assert sm.get_session(sid) is not None
        sm.close_session(sid)
        assert sm.get_session(sid) is None
