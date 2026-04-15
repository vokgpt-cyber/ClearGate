"""Tests for SessionStore -- SQLite-backed session persistence."""

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.session_store import SessionStore

UTC = timezone.utc


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_sessions.db"


@pytest.fixture()
def store(db_path: Path) -> SessionStore:
    s = SessionStore(db_path=db_path, ttl_minutes=60)
    yield s
    s.close()


def _make_session_kwargs(
    session_id: str = "test-session-1",
    locale: str = "ru",
    created_at: datetime | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "locale": locale,
        "created_at": created_at or datetime.now(UTC),
        "custom_entities": ["DISTANCE", "HOURS"],
        "enable_llm_layer": False,
        "spacy_model": "ru_core_news_sm",
        "registry_blob": b"encrypted-blob-placeholder",
        "docx_bytes": b"fake-docx-content",
        "docx_filename": "test.docx",
    }


class TestSessionStoreCRUD:
    """Basic create-read-update-delete operations."""

    def test_save_and_load(self, store: SessionStore) -> None:
        kwargs = _make_session_kwargs()
        store.save_session(**kwargs)
        data = store.load_session("test-session-1")
        assert data is not None
        assert data["session_id"] == "test-session-1"
        assert data["locale"] == "ru"
        assert data["docx_filename"] == "test.docx"
        assert data["registry_blob"] == b"encrypted-blob-placeholder"
        assert data["docx_bytes"] == b"fake-docx-content"

    def test_load_nonexistent_returns_none(self, store: SessionStore) -> None:
        assert store.load_session("nonexistent") is None

    def test_save_upsert(self, store: SessionStore) -> None:
        kwargs = _make_session_kwargs()
        store.save_session(**kwargs)
        kwargs["registry_blob"] = b"new-blob"
        store.save_session(**kwargs)
        data = store.load_session("test-session-1")
        assert data["registry_blob"] == b"new-blob"

    def test_delete_session(self, store: SessionStore) -> None:
        store.save_session(**_make_session_kwargs())
        store.delete_session("test-session-1")
        assert store.load_session("test-session-1") is None

    def test_delete_nonexistent_is_noop(self, store: SessionStore) -> None:
        store.delete_session("nonexistent")  # should not raise

    def test_save_with_none_blobs(self, store: SessionStore) -> None:
        kwargs = _make_session_kwargs()
        kwargs["registry_blob"] = None
        kwargs["docx_bytes"] = None
        kwargs["docx_filename"] = None
        store.save_session(**kwargs)
        data = store.load_session("test-session-1")
        assert data is not None
        assert data["registry_blob"] is None
        assert data["docx_bytes"] is None

    def test_save_response_docx(self, store: SessionStore) -> None:
        kwargs = _make_session_kwargs()
        kwargs["response_docx_bytes"] = b"response-content"
        kwargs["response_docx_filename"] = "response.docx"
        kwargs["deanonymized_docx_bytes"] = b"deanonymized-content"
        store.save_session(**kwargs)
        data = store.load_session("test-session-1")
        assert data["response_docx_bytes"] == b"response-content"
        assert data["response_docx_filename"] == "response.docx"
        assert data["deanonymized_docx_bytes"] == b"deanonymized-content"


class TestSessionStoreExpiry:
    """TTL enforcement."""

    def test_expired_session_not_loaded(self, store: SessionStore) -> None:
        old_time = datetime.now(UTC) - timedelta(minutes=120)
        kwargs = _make_session_kwargs(created_at=old_time)
        store.save_session(**kwargs)
        assert store.load_session("test-session-1") is None

    def test_fresh_session_loaded(self, store: SessionStore) -> None:
        kwargs = _make_session_kwargs(created_at=datetime.now(UTC))
        store.save_session(**kwargs)
        assert store.load_session("test-session-1") is not None

    def test_prune_expired(self, store: SessionStore) -> None:
        old = datetime.now(UTC) - timedelta(minutes=120)
        store.save_session(**_make_session_kwargs("old-1", created_at=old))
        store.save_session(**_make_session_kwargs("old-2", created_at=old))
        store.save_session(**_make_session_kwargs("fresh"))
        count = store.prune_expired()
        assert count == 2
        assert store.load_session("fresh") is not None


class TestSessionStoreList:
    """List sessions endpoint backing."""

    def test_list_sessions(self, store: SessionStore) -> None:
        store.save_session(**_make_session_kwargs("s1"))
        store.save_session(**_make_session_kwargs("s2"))
        sessions = store.list_sessions()
        ids = [s["session_id"] for s in sessions]
        assert "s1" in ids
        assert "s2" in ids

    def test_list_excludes_expired(self, store: SessionStore) -> None:
        old = datetime.now(UTC) - timedelta(minutes=120)
        store.save_session(**_make_session_kwargs("old", created_at=old))
        store.save_session(**_make_session_kwargs("fresh"))
        sessions = store.list_sessions()
        ids = [s["session_id"] for s in sessions]
        assert "old" not in ids
        assert "fresh" in ids

    def test_list_no_blob_columns(self, store: SessionStore) -> None:
        store.save_session(**_make_session_kwargs())
        sessions = store.list_sessions()
        for s in sessions:
            assert "registry_blob" not in s
            assert "docx_bytes" not in s


class TestSessionStoreSchema:
    """Database schema and initialization."""

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "sessions.db"
        s = SessionStore(db_path=deep)
        s.save_session(**_make_session_kwargs())
        s.close()
        assert deep.exists()

    def test_reopens_existing_db(self, db_path: Path) -> None:
        s1 = SessionStore(db_path=db_path)
        s1.save_session(**_make_session_kwargs())
        s1.close()
        s2 = SessionStore(db_path=db_path)
        data = s2.load_session("test-session-1")
        s2.close()
        assert data is not None
        assert data["session_id"] == "test-session-1"
