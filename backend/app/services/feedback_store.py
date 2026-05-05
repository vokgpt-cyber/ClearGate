"""SQLite-backed feedback storage with threaded replies.

Allows lawyers to submit feedback (bugs, suggestions, questions) from the UI.
Admins can reply and update status via admin endpoints. Feedback is retrieved
per-user (for the feedback widget) or in bulk (for admin dashboard).

Privacy: feedback may contain PII from the lawyer's work. Never log the text.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

UTC = timezone.utc

logger = structlog.get_logger(__name__)

_SCHEMA_VERSION = 1

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    username        TEXT NOT NULL,
    category        TEXT NOT NULL,
    text            TEXT NOT NULL,
    page_url        TEXT,
    session_id      TEXT,
    user_agent      TEXT,
    screenshot      BLOB,
    status          TEXT NOT NULL DEFAULT 'new',
    admin_reply     TEXT,
    admin_reply_at  TEXT,
    admin_user_id   TEXT
);
"""

_CREATE_META = """
CREATE TABLE IF NOT EXISTS feedback_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CREATE_INDICES = """
CREATE INDEX IF NOT EXISTS feedback_user_idx ON feedback(user_id);
CREATE INDEX IF NOT EXISTS feedback_status_idx ON feedback(status);
CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback(created_at DESC);
"""

_CREATE_INDEX_STATEMENTS = [
    stmt.strip()
    for stmt in _CREATE_INDICES.split(";")
    if stmt.strip()
]


@dataclass
class FeedbackRecord:
    """Single feedback entry with optional admin reply."""

    id: int
    created_at: str  # ISO 8601 timestamp
    user_id: str
    username: str
    category: str  # 'bug' | 'suggestion' | 'question'
    text: str
    page_url: str | None
    session_id: str | None
    user_agent: str | None
    screenshot: bytes | None  # BLOB from DB, already raw bytes
    status: str  # 'new' | 'in_progress' | 'resolved' | 'wontfix'
    admin_reply: str | None
    admin_reply_at: str | None
    admin_user_id: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization.

        Screenshot BLOB is base64-encoded for JSON transmission.
        """
        import base64

        screenshot_b64 = None
        if self.screenshot:
            screenshot_b64 = base64.b64encode(self.screenshot).decode("ascii")

        return {
            "id": self.id,
            "created_at": self.created_at,
            "user_id": self.user_id,
            "username": self.username,
            "category": self.category,
            "text": self.text,
            "page_url": self.page_url,
            "session_id": self.session_id,
            "user_agent": self.user_agent,
            "screenshot": screenshot_b64,
            "status": self.status,
            "admin_reply": self.admin_reply,
            "admin_reply_at": self.admin_reply_at,
            "admin_user_id": self.admin_user_id,
        }


class FeedbackStore:
    """Manage lawyer feedback submissions and admin replies."""

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
        logger.info("feedback_store.opened", path=str(db_path))

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_TABLE)
        cur.execute(_CREATE_META)
        for stmt in _CREATE_INDEX_STATEMENTS:
            cur.execute(stmt)
        cur.execute(
            "INSERT OR IGNORE INTO feedback_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            logger.info("feedback_store.closed")

    def submit(
        self,
        user_id: str,
        username: str,
        category: str,
        text: str,
        page_url: str | None = None,
        session_id: str | None = None,
        user_agent: str | None = None,
        screenshot: bytes | None = None,
    ) -> int:
        """Insert new feedback. Returns feedback id.

        Args:
            user_id: User submitting the feedback.
            username: Username (denormalized for convenience).
            category: 'bug' | 'suggestion' | 'question'.
            text: Feedback text (may contain PII).
            page_url: URL where feedback was submitted from.
            session_id: Session ID if applicable.
            user_agent: Browser user agent.
            screenshot: Optional screenshot as raw bytes.

        Returns:
            Newly inserted feedback id.
        """
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO feedback
            (created_at, user_id, username, category, text, page_url,
             session_id, user_agent, screenshot, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                user_id,
                username,
                category,
                text,
                page_url,
                session_id,
                user_agent,
                screenshot,
                "new",
            ),
        )
        self._conn.commit()
        feedback_id = cur.lastrowid
        logger.info(
            "feedback.submitted",
            feedback_id=feedback_id,
            user_id=user_id,
            category=category,
        )
        return feedback_id

    def list_for_user(self, user_id: str, limit: int = 50) -> list[FeedbackRecord]:
        """Fetch all feedback submitted by a user (with admin replies).

        Used by the frontend feedback widget to display the user's own tickets.

        Args:
            user_id: User to fetch feedback for.
            limit: Maximum number of records to return.

        Returns:
            List of FeedbackRecord ordered newest first.
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, user_id, username, category, text,
                   page_url, session_id, user_agent, screenshot, status,
                   admin_reply, admin_reply_at, admin_user_id
            FROM feedback
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_all(
        self, status: str | None = None, limit: int = 200
    ) -> list[FeedbackRecord]:
        """Fetch all feedback (for admin dashboard).

        Args:
            status: Filter by status ('new', 'in_progress', 'resolved', 'wontfix').
                   If None, return all statuses.
            limit: Maximum number of records.

        Returns:
            List of FeedbackRecord ordered newest first.
        """
        cur = self._conn.cursor()
        if status is None:
            cur.execute(
                """
                SELECT id, created_at, user_id, username, category, text,
                       page_url, session_id, user_agent, screenshot, status,
                       admin_reply, admin_reply_at, admin_user_id
                FROM feedback
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cur.execute(
                """
                SELECT id, created_at, user_id, username, category, text,
                       page_url, session_id, user_agent, screenshot, status,
                       admin_reply, admin_reply_at, admin_user_id
                FROM feedback
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
        rows = cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_by_id(self, feedback_id: int) -> FeedbackRecord | None:
        """Fetch a single feedback entry by id."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, user_id, username, category, text,
                   page_url, session_id, user_agent, screenshot, status,
                   admin_reply, admin_reply_at, admin_user_id
            FROM feedback
            WHERE id = ?
            """,
            (feedback_id,),
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def reply(
        self,
        feedback_id: int,
        admin_user_id: str,
        reply: str,
        new_status: str | None = None,
    ) -> bool:
        """Admin reply to feedback. Sets reply text, timestamp, and optionally status.

        Args:
            feedback_id: Feedback id to reply to.
            admin_user_id: Admin's user id.
            reply: Reply text.
            new_status: Optional new status ('in_progress', 'resolved', 'wontfix').

        Returns:
            True if found and updated, False otherwise.
        """
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()

        if new_status:
            cur.execute(
                """
                UPDATE feedback
                SET admin_reply = ?, admin_reply_at = ?, admin_user_id = ?, status = ?
                WHERE id = ?
                """,
                (reply, now, admin_user_id, new_status, feedback_id),
            )
        else:
            cur.execute(
                """
                UPDATE feedback
                SET admin_reply = ?, admin_reply_at = ?, admin_user_id = ?
                WHERE id = ?
                """,
                (reply, now, admin_user_id, feedback_id),
            )

        self._conn.commit()
        updated = cur.rowcount > 0
        if updated:
            logger.info(
                "feedback.replied",
                feedback_id=feedback_id,
                admin_user_id=admin_user_id,
            )
        return updated

    def update_status(self, feedback_id: int, status: str) -> bool:
        """Update feedback status without a reply.

        Args:
            feedback_id: Feedback id to update.
            status: New status ('new', 'in_progress', 'resolved', 'wontfix').

        Returns:
            True if found and updated.
        """
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE feedback SET status = ? WHERE id = ?",
            (status, feedback_id),
        )
        self._conn.commit()
        updated = cur.rowcount > 0
        if updated:
            logger.info("feedback.status_updated", feedback_id=feedback_id, status=status)
        return updated

    @staticmethod
    def _row_to_record(row: tuple[Any, ...]) -> FeedbackRecord:
        """Convert SQL row to FeedbackRecord."""
        return FeedbackRecord(
            id=row[0],
            created_at=row[1],
            user_id=row[2],
            username=row[3],
            category=row[4],
            text=row[5],
            page_url=row[6],
            session_id=row[7],
            user_agent=row[8],
            screenshot=row[9],
            status=row[10],
            admin_reply=row[11],
            admin_reply_at=row[12],
            admin_user_id=row[13],
        )
