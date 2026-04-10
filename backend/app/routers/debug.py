"""Debug / diagnostics endpoints.

These endpoints exist ONLY to support frontend diagnostic instrumentation
during active development (e.g. tracing the selection → popover chain in
iter3.2). They are intentionally kept in a separate router so they can be
disabled or removed wholesale in a single place before any production cut.

SECURITY NOTE
-------------
The VELUM security model forbids logging of original document text,
entity mapping tables, or encryption keys. This router MUST NOT persist
any such data. The `selection-log` endpoint accepts free-form JSON but
the frontend is responsible for sending ONLY metadata (lengths, offsets,
booleans, coordinates). On the server side we make an additional defensive
pass that scrubs any key named `text`, `sample`, `content`, `value`,
`placeholder`, or `mapping` before writing to disk.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/debug", tags=["debug"])

# Logs live under backend/logs/ — the backend process cwd is typically
# `backend/`, so a plain relative path is enough. We resolve against this
# file's location for robustness against unexpected cwds.
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_SELECTION_LOG = _LOG_DIR / "selection-diagnostic.jsonl"

_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "text",
        "sample",
        "content",
        "value",
        "placeholder",
        "mapping",
        "original",
        "plaintext",
        "plain_text",
    }
)


def _scrub(value: Any) -> Any:
    """Recursively strip any key whose name hints at document content.

    Defense-in-depth against a frontend log accidentally including a
    text sample. We drop the key entirely rather than mask it so the
    resulting log file can NEVER be used to reconstruct selections.
    """
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if k.lower() not in _FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class SelectionLogEntry(BaseModel):
    """One diagnostic breadcrumb from the frontend selection pipeline.

    Fields are deliberately permissive — this is a debug channel, not a
    stable API contract.
    """

    label: str = Field(..., description="Log point identifier, e.g. 'A mouseup'")
    data: dict[str, Any] = Field(default_factory=dict)
    session: str | None = Field(
        default=None,
        description="Opaque id generated per frontend mount, for grouping",
    )


@router.post("/selection-log")
async def append_selection_log(entry: SelectionLogEntry) -> dict[str, str]:
    """Append one scrubbed diagnostic line to the selection log file.

    Returns a minimal ack so the frontend fetch promise resolves.
    """
    safe_data = _scrub(entry.data)
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "session": entry.session,
        "label": entry.label,
        "data": safe_data,
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _SELECTION_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("debug.selection_log.write_failed", error=str(e))
        return {"status": "error"}
    return {"status": "ok"}


@router.post("/selection-log/clear")
async def clear_selection_log() -> dict[str, str]:
    """Truncate the selection log file.

    Called by the frontend on fresh workspace mount so each diagnostic
    session starts clean and Claude can read the file without wading
    through stale entries from previous runs.
    """
    try:
        _SELECTION_LOG.write_bytes(b"")
    except OSError as e:
        logger.warning("debug.selection_log.clear_failed", error=str(e))
        return {"status": "error"}
    return {"status": "ok"}
