"""Admin endpoints: users, feedback, events, analytics, errors.

All endpoints require admin role. These are used by the admin dashboard
and IT support tools.

Privacy: Some endpoints return audit data; be careful not to include
request/response bodies or sensitive payloads in responses.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user
from app.services.user_store import UserRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# -----------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------


class AdminUserListItem(BaseModel):
    """User info in admin list response."""

    user_id: str
    username: str
    is_active: bool
    created_at: str


class AdminUserListResponse(BaseModel):
    """Response from GET /api/admin/users."""

    users: list[AdminUserListItem]
    total: int


class AdminUserUpdateRequest(BaseModel):
    """Request to update a user (PATCH /api/admin/users/{user_id})."""

    is_active: bool | None = None
    # password: str | None = None  # for future: password reset
    # role: str | None = None      # for future: role assignment


class AdminUserUpdateResponse(BaseModel):
    """Response from user update."""

    user_id: str
    updated: bool


class FeedbackReplyRequest(BaseModel):
    """Request to reply to feedback (PATCH /api/admin/feedback/{id})."""

    reply: str = Field(..., min_length=1, max_length=10_000)
    new_status: str | None = Field(
        None, pattern="^(new|in_progress|resolved|wontfix)$"
    )


class FeedbackReplyResponse(BaseModel):
    """Response from feedback reply."""

    feedback_id: int
    updated: bool


class AdminFeedbackItem(BaseModel):
    """Feedback item in admin list."""

    id: int
    created_at: str
    user_id: str
    username: str
    category: str
    text: str
    status: str
    admin_reply: str | None
    admin_reply_at: str | None


class AdminFeedbackListResponse(BaseModel):
    """Response from GET /api/admin/feedback."""

    items: list[AdminFeedbackItem]
    total: int


class AnalyticsSummary(BaseModel):
    """Pre-aggregated analytics summary for a time window."""

    date_range_days: int
    requests_per_day: list[dict[str, int | str]]  # [{'date': '2026-04-28', 'count': 42}]
    latency_p50_ms_per_day: list[dict[str, int | str | float]]
    latency_p95_ms_per_day: list[dict[str, int | str | float]]
    error_rate_per_day: list[dict[str, int | str | float]]
    active_users_last_period: int
    top_endpoints: list[dict[str, str | int]]  # [{'endpoint': 'POST /api/sessions', 'requests': 123}]


class AdminErrorItem(BaseModel):
    """Error entry in admin errors list."""

    id: int
    timestamp: str
    user_id: str | None
    severity: str
    message: str
    page_url: str | None


class AdminErrorListResponse(BaseModel):
    """Response from GET /api/admin/errors."""

    items: list[AdminErrorItem]
    total: int


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def require_admin(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserRecord:
    """FastAPI dependency: require authenticated user with admin role.

    Checks the role attribute added by Phase 3's UserStore schema migration.
    LDAP-authenticated users have their role derived from AD group membership;
    locally-authenticated users carry whatever role was set on their account
    (admin via `cleargate-admin create-user --admin` or via /api/admin/users
    PATCH from another admin).

    Args:
        user: Authenticated user from get_current_user.

    Returns:
        The user record if role == 'admin'.

    Raises:
        HTTPException 403 if not admin. Logs the attempted access so admins
        can spot probing in /admin/errors.
    """
    role = getattr(user, "role", "lawyer")
    if role != "admin":
        logger.warning(
            "require_admin.denied",
            user_id=user.user_id,
            username=getattr(user, "username", None),
            actual_role=role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# -----------------------------------------------------------------------
# DI
# -----------------------------------------------------------------------


def get_user_store_from_request():
    """Dependency stub."""
    raise RuntimeError("UserStore dependency not wired up")


def get_feedback_store_from_request():
    """Dependency stub."""
    raise RuntimeError("FeedbackStore dependency not wired up")


def get_error_store_from_request():
    """Dependency stub."""
    raise RuntimeError("ErrorStore dependency not wired up")


# -----------------------------------------------------------------------
# Users endpoints
# -----------------------------------------------------------------------


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    admin: Annotated[UserRecord, Depends(require_admin)],
    user_store: Annotated[object, Depends(get_user_store_from_request)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserListResponse:
    """List all users with pagination.

    Args:
        admin: Authenticated admin user.
        user_store: UserStore instance (injected via Depends).
        limit: Number of results.
        offset: Starting offset.

    Returns:
        List of users and total count.
    """

    # TODO: Implement pagination in UserStore.
    # For now, return all users and trust the limit.
    all_users = user_store.list_users()
    users = all_users[offset : offset + limit]

    items = [
        AdminUserListItem(
            user_id=u.user_id,
            username=u.username,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]

    logger.info("admin.users.listed", admin_id=admin.user_id, count=len(items))

    return AdminUserListResponse(users=items, total=len(all_users))


@router.patch("/users/{user_id}", response_model=AdminUserUpdateResponse)
async def update_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    admin: Annotated[UserRecord, Depends(require_admin)],
    user_store: Annotated[object, Depends(get_user_store_from_request)],
) -> AdminUserUpdateResponse:
    """Update a user's settings (is_active, etc.).

    Args:
        user_id: User to update.
        request: Update payload.
        admin: Authenticated admin.
        user_store: UserStore instance (injected via Depends).

    Returns:
        Update result.
    """

    updated = False
    if request.is_active is not None:
        updated = user_store.set_active(user_id, request.is_active)

    logger.info(
        "admin.user.updated",
        target_user_id=user_id,
        admin_user_id=admin.user_id,
        is_active=request.is_active,
    )

    return AdminUserUpdateResponse(user_id=user_id, updated=updated)


# -----------------------------------------------------------------------
# Feedback endpoints
# -----------------------------------------------------------------------


@router.get("/feedback", response_model=AdminFeedbackListResponse)
async def list_feedback(
    admin: Annotated[UserRecord, Depends(require_admin)],
    feedback_store: Annotated[object, Depends(get_feedback_store_from_request)],
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> AdminFeedbackListResponse:
    """List feedback items (optionally filtered by status).

    Args:
        admin: Authenticated admin.
        feedback_store: FeedbackStore instance (injected via Depends).
        status: Filter by status (new, in_progress, resolved, wontfix).
        limit: Maximum results.

    Returns:
        List of feedback and total count.
    """

    records = feedback_store.list_all(status=status, limit=limit)
    items = [
        AdminFeedbackItem(
            id=r.id,
            created_at=r.created_at,
            user_id=r.user_id,
            username=r.username,
            category=r.category,
            text=r.text,
            status=r.status,
            admin_reply=r.admin_reply,
            admin_reply_at=r.admin_reply_at,
        )
        for r in records
    ]

    logger.info(
        "admin.feedback.listed",
        admin_id=admin.user_id,
        count=len(items),
        status_filter=status,
    )

    return AdminFeedbackListResponse(items=items, total=len(items))


@router.patch("/feedback/{feedback_id}", response_model=FeedbackReplyResponse)
async def reply_to_feedback(
    feedback_id: int,
    request: FeedbackReplyRequest,
    admin: Annotated[UserRecord, Depends(require_admin)],
    feedback_store: Annotated[object, Depends(get_feedback_store_from_request)],
) -> FeedbackReplyResponse:
    """Admin reply to feedback with optional status update.

    Args:
        feedback_id: Feedback to reply to.
        request: Reply text and optional new status.
        admin: Authenticated admin.
        feedback_store: FeedbackStore instance (injected via Depends).

    Returns:
        Reply result.
    """

    updated = feedback_store.reply(
        feedback_id=feedback_id,
        admin_user_id=admin.user_id,
        reply=request.reply,
        new_status=request.new_status,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feedback {feedback_id} not found",
        )

    logger.info(
        "admin.feedback.replied",
        feedback_id=feedback_id,
        admin_id=admin.user_id,
    )

    return FeedbackReplyResponse(feedback_id=feedback_id, updated=updated)


# -----------------------------------------------------------------------
# Errors endpoint
# -----------------------------------------------------------------------


@router.get("/errors", response_model=AdminErrorListResponse)
async def list_errors(
    admin: Annotated[UserRecord, Depends(require_admin)],
    error_store: Annotated[object, Depends(get_error_store_from_request)],
    hours: Annotated[int, Query(ge=1, le=8760)] = 168,  # default 7 days
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> AdminErrorListResponse:
    """List recent client and server errors.

    Args:
        admin: Authenticated admin.
        error_store: ErrorStore instance (injected via Depends).
        hours: Look back this many hours.
        limit: Maximum results.

    Returns:
        List of errors and total count.
    """

    records = error_store.list_recent(hours=hours, limit=limit)
    items = [
        AdminErrorItem(
            id=r.id,
            timestamp=r.timestamp,
            user_id=r.user_id,
            severity=r.severity,
            message=r.message,
            page_url=r.page_url,
        )
        for r in records
    ]

    logger.info(
        "admin.errors.listed",
        admin_id=admin.user_id,
        count=len(items),
        hours=hours,
    )

    return AdminErrorListResponse(items=items, total=len(items))


# -----------------------------------------------------------------------
# Analytics stub (Phase 3 will implement)
# -----------------------------------------------------------------------


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    admin: Annotated[UserRecord, Depends(require_admin)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AnalyticsSummary:
    """Pre-aggregated analytics summary.

    TODO: Phase 3 will implement actual aggregation from audit_log.
    For now, return stub data.

    Args:
        admin: Authenticated admin.
        days: Look back this many days.

    Returns:
        Analytics summary.
    """
    logger.info(
        "admin.analytics.queried",
        admin_id=admin.user_id,
        days=days,
    )

    return AnalyticsSummary(
        date_range_days=days,
        requests_per_day=[],  # TODO
        latency_p50_ms_per_day=[],  # TODO
        latency_p95_ms_per_day=[],  # TODO
        error_rate_per_day=[],  # TODO
        active_users_last_period=0,  # TODO
        top_endpoints=[],  # TODO
    )
