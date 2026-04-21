"""SQLite-backed user persistence for CLEARGATE.

Stores local user accounts with Argon2id-hashed passwords for the pilot
deployment.  Intentionally minimal: username + password + active flag.
No email, no role, no password history -- those are Sprint C+ concerns.

Privacy: we never log the password hash itself.  Usernames are logged
(they are not PII under our threat model -- they are assigned by the
admin, not self-registered).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

UTC = timezone.utc

logger = structlog.get_logger(__name__)

_SCHEMA_VERSION = 1

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""

_CREATE_META = """
CREATE TABLE IF NOT EXISTS user_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class UserRecord:
    """Lightweight struct returned by UserStore.get_* methods."""

    __slots__ = (
        "user_id",
        "username",
        "password_hash",
        "is_active",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        is_active: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.password_hash = password_hash
        self.is_active = is_active
        self.created_at = created_at
        self.updated_at = updated_at

    def to_public_dict(self) -> dict[str, Any]:
        """Dict safe to return over HTTP — never includes the password hash."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }


class UserStore:
    """SQLite-backed user persistence."""

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
        logger.info("user_store.opened", path=str(db_path))

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_TABLE)
        cur.execute(_CREATE_META)
        cur.execute(
            "INSERT OR IGNORE INTO user_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password_hash: str,
        user_id: str | None = None,
        is_active: bool = True,
    ) -> UserRecord:
        """Insert a new user.  Raises sqlite3.IntegrityError on duplicate username."""
        uid = user_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        try:
            self._conn.execute(
                """
                INSERT INTO users (
                    user_id, username, password_hash, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uid, username, password_hash, int(is_active), now_iso, now_iso),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            self._conn.rollback()
            raise
        logger.info("user_store.created", user_id=uid, username=username)
        return UserRecord(
            user_id=uid,
            username=username,
            password_hash=password_hash,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

    def update_password(self, user_id: str, new_password_hash: str) -> bool:
        """Replace a user's password hash.  Returns True iff the user existed."""
        now_iso = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            """
            UPDATE users
               SET password_hash = ?, updated_at = ?
             WHERE user_id = ?
            """,
            (new_password_hash, now_iso, user_id),
        )
        self._conn.commit()
        ok = cur.rowcount > 0
        if ok:
            logger.info("user_store.password_updated", user_id=user_id)
        return ok

    def set_active(self, user_id: str, is_active: bool) -> bool:
        """Enable or disable a user without deleting the row.  Returns True iff changed."""
        now_iso = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            """
            UPDATE users
               SET is_active = ?, updated_at = ?
             WHERE user_id = ?
            """,
            (int(is_active), now_iso, user_id),
        )
        self._conn.commit()
        ok = cur.rowcount > 0
        if ok:
            logger.info("user_store.active_toggled", user_id=user_id, is_active=is_active)
        return ok

    def delete_user(self, user_id: str) -> bool:
        """Permanently remove a user row.  Returns True iff deleted."""
        cur = self._conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self._conn.commit()
        ok = cur.rowcount > 0
        if ok:
            logger.info("user_store.deleted", user_id=user_id)
        return ok

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_username(self, username: str) -> UserRecord | None:
        """Look up a user by username (case-insensitive via COLLATE NOCASE)."""
        cur = self._conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(cur, row)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        """Look up a user by UUID."""
        cur = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(cur, row)

    def list_users(self) -> list[UserRecord]:
        """Return all users ordered by creation time."""
        cur = self._conn.execute(
            "SELECT * FROM users ORDER BY created_at ASC"
        )
        return [self._row_to_record(cur, row) for row in cur.fetchall()]

    def count(self) -> int:
        """Return total user count (used by admin CLI + seeding logic)."""
        cur = self._conn.execute("SELECT COUNT(*) FROM users")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.info("user_store.closed")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(cursor: sqlite3.Cursor, row: tuple) -> UserRecord:
        columns = [desc[0] for desc in cursor.description]
        data = dict(zip(columns, row))
        created = datetime.fromisoformat(data["created_at"])
        updated = datetime.fromisoformat(data["updated_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return UserRecord(
            user_id=data["user_id"],
            username=data["username"],
            password_hash=data["password_hash"],
            is_active=bool(data["is_active"]),
            created_at=created,
            updated_at=updated,
        )
