"""Client error reporting endpoint.

Frontend calls POST /api/client-errors to report errors caught by window.onerror
or try/catch blocks. Errors are recorded in the error_store (append-only log)
and visible to admins via GET /api/admin/errors.

Requires auth (so we know which user reported) but lenient on validation
(frontend errors can be messy).
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user
from app.services.user_store import UserRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/client-errors", tags=["errors"])


# -----------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------


class ClientErrorReport(BaseModel):
    """Client error submitted from the frontend."""

    message: str = Field(..., min_length=1, max_length=10_000)
    stack: str | None = Field(None, max_length=100_000)
    page_url: str | None = None
    user_agent: str | None = None
    severity: str = Field(default="error", pattern="^(error|warning)$")


# -----------------------------------------------------------------------
# DI
# -----------------------------------------------------------------------


def get_error_store_from_request():
    """Dependency stub -- overridden in main.py lifespan."""
    raise RuntimeError(
        "ErrorStore dependency not wired up; check main.py lifespan initialisation"
    )


# -----------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def report_client_error(
    request: ClientErrorReport,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    error_store: Annotated[object, Depends(get_error_store_from_request)],
) -> Response:
    """Record a client-side error for admin diagnostics.

    Called from frontend window.onerror or try/catch handlers. The error
    is recorded with minimal validation (frontend errors are messy).

    Args:
        request: Error details.
        current_user: Authenticated user.
        error_store: ErrorStore instance (injected via Depends).

    Returns:
        204 No Content.
    """

    error_id = error_store.report_client_error(
        user_id=current_user.user_id,
        session_id=None,  # could be extracted from request if available
        page_url=request.page_url,
        message=request.message,
        stack=request.stack,
        user_agent=request.user_agent,
        severity=request.severity,
    )

    logger.info(
        "client_error.received",
        error_id=error_id,
        user_id=current_user.user_id,
        severity=request.severity,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
