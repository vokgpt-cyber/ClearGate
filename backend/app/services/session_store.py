"""SQLite-backed session persistence for VELUM.

Stores session metadata, encrypted EntityRegistry blobs, and DOCX bytes
so that sessions survive backend restarts.  Uses the same AES-256-GCM
encryption that EntityRegistry already provides -- no new crypto primitives.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

UTC = timezone.utc

logger = structlog.get_logger(__name__)

_SCHEMA_VERSION = 1

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    locale          TEXT NOT NULL DEFAULT 'ru',
    created_at      TEXT NOT NULL,
    custom_entities TEXT NOT NULL DEFAULT '[]',
    enable_llm_layer INTEGER NOT NULL DEFAULT 0,
    spacy_model     TEXT DEFAULT 'ru_core_news_sm',
    registry_blob   BLOB,
    docx_bytes      BLOB,
    docx_filename   TEXT,
    response_docx_bytes     BLOB,
    response_docx_filename  TEXT,
    deanonymized_docx_bytes BLOB,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SessionStore:
    """SQLite-backed session persistence."""

    def __init__(self, db_path: Path, ttl_minutes: int = 1440) -> None:
        self._db_path = db_path
        self._ttl_minutes = ttl_minutes
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        logger.info("session_store.opened", path=str(db_path))

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_TABLE)
        cur.execute(_CREATE_META)
        cur.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()

    def save_session(
        self,
        session_id: str,
        locale: str,
        created_at: datetime,
        custom_entities: list[str],
        enable_llm_layer: bool,
        spacy_model: str | None,
        registry_blob: bytes | None,
        docx_bytes: bytes | None = None,
        docx_filename: str | None = None,
        response_docx_bytes: bytes | None = None,
        response_docx_filename: str | None = None,
        deanonymized_docx_bytes: bytes | None = None,
    ) -> None:
        """Upsert a session to disk."""
        import json
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO sessions (
                session_id, locale, created_at, custom_entities,
                enable_llm_layer, spacy_model, registry_blob,
                docx_bytes, docx_filename,
                response_docx_bytes, response_docx_filename,
                deanonymized_docx_bytes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                registry_blob = excluded.registry_blob,
                docx_bytes = excluded.docx_bytes,
                docx_filename = excluded.docx_filename,
                response_docx_bytes = excluded.response_docx_bytes,
                response_docx_filename = excluded.response_docx_filename,
                deanonymized_docx_bytes = excluded.deanonymized_docx_bytes,
                updated_at = excluded.updated_at
            """,
            (
                session_id, locale, created_at.isoformat(),
                json.dumps(custom_entities), int(enable_llm_layer),
                spacy_model, registry_blob, docx_bytes, docx_filename,
                response_docx_bytes, response_docx_filename,
                deanonymized_docx_bytes, now,
            ),
        )
        self._conn.commit()
        logger.debug("session_store.saved", session_id=session_id)

    def delete_session(self, session_id: str) -> None:
        """Remove a session from disk."""
        self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()
        logger.info("session_store.deleted", session_id=session_id)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a single session row, or None if missing/expired."""
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        data = self._row_to_dict(cur, row)
        if self._is_expired(data):
            self.delete_session(session_id)
            return None
        return data

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return metadata for all non-expired sessions (no blobs)."""
        cur = self._conn.execute(
            """
            SELECT session_id, locale, created_at, custom_entities,
                   enable_llm_layer, spacy_model, docx_filename,
                   response_docx_filename, updated_at
            FROM sessions
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            data = self._row_to_dict(cur, row)
            if self._is_expired(data):
                self.delete_session(data["session_id"])
                continue
            result.append(data)
        return result

    def prune_expired(self) -> int:
        """Delete all expired sessions.  Returns count deleted."""
        cutoff = (
            datetime.now(UTC) - timedelta(minutes=self._ttl_minutes)
        ).isoformat()
        cur = self._conn.execute(
            "DELETE FROM sessions WHERE created_at < ?", (cutoff,)
        )
        self._conn.commit()
        count = cur.rowcount
        if count:
            logger.info("session_store.pruned", count=count)
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.info("session_store.closed")

    @staticmethod
    def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def _is_expired(self, data: dict[str, Any]) -> bool:
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return datetime.now(UTC) - created > timedelta(minutes=self._ttl_minutes)
