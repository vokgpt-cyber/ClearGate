"""SQLite-backed client and server error logging (append-only).

Records both client-side errors (via POST /api/client-errors) and server
errors (via telemetry middleware). Used for admin dashboard diagnostics
and error rate trending.

Privacy: errors may contain PII. Never log the full error text at WARNING
level; only log at DEBUG level or write to the database with no duplication.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

UTC = timezone.utc

logger = structlog.get_logger(__name__)

_SCHEMA_VERSION = 1

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS client_errors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    user_id      TEXT,
    session_id   TEXT,
    page_url     TEXT,
    message      TEXT NOT NULL,
    stack        TEXT,
    user_agent   TEXT,
    severity     TEXT DEFAULT 'error'
);
"""

_CREATE_META = """
CREATE TABLE IF NOT EXISTS error_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CREATE_INDICES = """
CREATE INDEX IF NOT EXISTS error_timestamp_idx ON client_errors(timestamp DESC);
CREATE INDEX IF NOT EXISTS error_user_idx ON client_errors(user_id);
CREATE INDEX IF NOT EXISTS error_severity_idx ON client_errors(severity);
"""

_CREATE_INDEX_STATEMENTS = [
    stmt.strip()
    for stmt in _CREATE_INDICES.split(";")
    if stmt.strip()
]


@dataclass
class ErrorRecord:
    """Single error entry from the error log."""

    id: int
    timestamp: str  # ISO 8601
    user_id: str | None
    session_id: str | None
    page_url: str | None
    message: str
    stack: str | None
    user_agent: str | None
    severity: str  # 'error' | 'warning'

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "page_url": self.page_url,
            "message": self.message,
            "stack": self.stack,
            "user_agent": self.user_agent,
            "severity": self.severity,
        }


class ErrorStore:
    """Append-only error log for client and server errors."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        logger.info("error_store.opened", path=str(db_path))

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_TABLE)
        cur.execute(_CREATE_META)
        for stmt in _CREATE_INDEX_STATEMENTS:
            cur.execute(stmt)
        cur.execute(
            "INSERT OR IGNORE INTO error_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            logger.info("error_store.closed")

    def report_client_error(
        self,
        user_id: str | None,
        session_id: str | None,
        page_url: str | None,
        message: str,
        stack: str | None = None,
        user_agent: str | None = None,
        severity: str = "error",
    ) -> int:
        """Record a client-side error.

        Called from POST /api/client-errors endpoint. Errors are messy and
        missing fields are expected.

        Args:
            user_id: User who reported the error (may be None if pre-auth).
            session_id: Session context (may be None).
            page_url: Page where the error occurred.
            message: Error message (required).
            stack: Stack trace (optional).
            user_agent: Browser user agent (optional).
            severity: 'error' | 'warning'.

        Returns:
            Newly inserted error id.
        """
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO client_errors
            (timestamp, user_id, session_id, page_url, message, stack, user_agent, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, user_id, session_id, page_url, message, stack, user_agent, severity),
        )
        self._conn.commit()
        error_id = cur.lastrowid
        logger.debug(
            "client_error.reported",
            error_id=error_id,
            user_id=user_id,
            severity=severity,
        )
        return error_id

    def report_server_error(
        self,
        message: str,
        user_id: str | None = None,
        session_id: str | None = None,
        page_url: str | None = None,
        stack: str | None = None,
        severity: str = "error",
    ) -> int:
        """Record a server-side error (called from telemetry middleware on 5xx).

        Args:
            message: Error message.
            user_id: User associated with the request.
            session_id: Session context.
            page_url: Request path/URL.
            stack: Server stack trace.
            severity: 'error' | 'warning'.

        Returns:
            Newly inserted error id.
        """
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO client_errors
            (timestamp, user_id, session_id, page_url, message, stack, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, user_id, session_id, page_url, message, stack, severity),
        )
        self._conn.commit()
        error_id = cur.lastrowid
        logger.info(
            "server_error.reported",
            error_id=error_id,
            user_id=user_id,
            severity=severity,
        )
        return error_id

    def list_recent(self, hours: int = 168, limit: int = 500) -> list[ErrorRecord]:
        """Fetch recent errors (default: last 7 days).

        Args:
            hours: Look back this many hours (default 168 = 7 days).
            limit: Maximum records to return.

        Returns:
            List of ErrorRecord ordered newest first.
        """
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, timestamp, user_id, session_id, page_url, message,
                   stack, user_agent, severity
            FROM client_errors
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_by_severity(self, hours: int = 168) -> dict[str, int]:
        """Count errors by severity in the given time window.

        Args:
            hours: Look back this many hours.

        Returns:
            Dict mapping severity -> count.
        """
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT severity, COUNT(*) as count
            FROM client_errors
            WHERE timestamp >= ?
            GROUP BY severity
            """,
            (cutoff,),
        )
        return dict(cur.fetchall())

    def prune_older_than(self, days: int) -> int:
        """Delete errors older than N days (for storage hygiene).

        Args:
            days: Delete errors older than this.

        Returns:
            Number of rows deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        cur = self._conn.cursor()
        cur.execute("DELETE FROM client_errors WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.info("error_store.pruned", count=deleted, days=days)
        return deleted

    @staticmethod
    def _row_to_record(row: tuple[Any, ...]) -> ErrorRecord:
        """Convert SQL row to ErrorRecord."""
        return ErrorRecord(
            id=row[0],
            timestamp=row[1],
            user_id=row[2],
            session_id=row[3],
            page_url=row[4],
            message=row[5],
            stack=row[6],
            user_agent=row[7],
            severity=row[8],
        )
