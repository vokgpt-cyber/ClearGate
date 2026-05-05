"""Admin endpoints: users, feedback, events, analytics, errors.

All endpoints require admin role. These are used by the admin dashboard
and IT support tools.

Privacy: Some endpoints return audit data; be careful not to include
request/response bodies or sensitive payloads in responses.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user
from app.services.auth import get_auth_service
from app.services.session_manager import SessionManager
from app.services.user_store import UserRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])
UTC = timezone.utc


# -----------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------


class AdminUserListItem(BaseModel):
    """User info in admin list response."""

    user_id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    role: str = "lawyer"
    is_active: bool
    ldap_dn: str | None = None
    created_at: str
    last_login_at: str | None = None


class AdminUserListResponse(BaseModel):
    """Response from GET /api/admin/users."""

    users: list[AdminUserListItem]
    total: int


class AdminUserUpdateRequest(BaseModel):
    """Request to update a user (PATCH /api/admin/users/{user_id})."""

    is_active: bool | None = None
    role: str | None = Field(None, pattern="^(admin|lawyer)$")
    email: str | None = None
    display_name: str | None = None
    new_password: str | None = Field(None, min_length=8, max_length=512)


class AdminUserCreateRequest(BaseModel):
    """Request to create a local user."""

    username: str = Field(..., min_length=2, max_length=128)
    password: str = Field(..., min_length=8, max_length=512)
    email: str | None = None
    display_name: str | None = None
    role: str = Field("lawyer", pattern="^(admin|lawyer)$")


class AdminUserUpdateResponse(BaseModel):
    """Response from user update."""

    user_id: str
    updated: bool


class AdminSyncADResponse(BaseModel):
    """Response from AD synchronization."""

    created: int = 0
    updated: int = 0
    deactivated: int = 0


class FeedbackReplyRequest(BaseModel):
    """Request to reply to feedback (PATCH /api/admin/feedback/{id})."""

    reply: str | None = Field(None, min_length=1, max_length=10_000)
    admin_reply: str | None = Field(None, min_length=1, max_length=10_000)
    new_status: str | None = Field(
        None, pattern="^(new|in_progress|resolved|wontfix)$"
    )
    status: str | None = Field(None, pattern="^(new|in_progress|resolved|wontfix)$")


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


class AdminAnalyticsResponse(BaseModel):
    """Dashboard analytics shape consumed by the frontend."""

    total_sessions: int = 0
    anonymize_latency: dict[str, int] = Field(
        default_factory=lambda: {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0}
    )
    sessions_per_day: list[dict[str, int | str]] = Field(default_factory=list)
    top_entity_types: list[dict[str, int | str]] = Field(default_factory=list)
    active_users_7d: int = 0
    error_rate_percent: float = 0.0


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


def _parse_admin_range(
    from_date: str | None,
    to_date: str | None,
    days: int,
) -> tuple[datetime, datetime]:
    today = datetime.now(UTC).date()
    if from_date:
        start_date = date.fromisoformat(from_date)
    else:
        start_date = today - timedelta(days=days - 1)
    if to_date:
        end_date = date.fromisoformat(to_date)
    else:
        end_date = today
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC),
        datetime.combine(end_date, time.max, tzinfo=UTC),
    )


def _parse_iso_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _percentile(values: list[float], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(round(ordered[0]))
    pos = (len(ordered) - 1) * p
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


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


def _to_admin_user_item(record: UserRecord) -> AdminUserListItem:
    """Convert a UserRecord into the admin-facing public schema."""
    return AdminUserListItem(
        user_id=record.user_id,
        username=record.username,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        is_active=record.is_active,
        ldap_dn=record.ldap_dn,
        created_at=record.created_at.isoformat(),
        last_login_at=(
            record.last_login_at.isoformat() if record.last_login_at else None
        ),
    )


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

    all_users = user_store.list_all()
    users = all_users[offset : offset + limit]

    items = [_to_admin_user_item(u) for u in users]

    logger.info("admin.users.listed", admin_id=admin.user_id, count=len(items))

    return AdminUserListResponse(users=items, total=len(all_users))


@router.post(
    "/users",
    response_model=AdminUserListItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: AdminUserCreateRequest,
    admin: Annotated[UserRecord, Depends(require_admin)],
    user_store: Annotated[object, Depends(get_user_store_from_request)],
) -> AdminUserListItem:
    """Create a local account."""
    auth = get_auth_service()
    try:
        record = user_store.create_user(
            username=request.username.strip(),
            password_hash=auth.hash_password(request.password),
            is_active=True,
            role=request.role,
            email=request.email,
            display_name=request.display_name,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists or cannot be created",
        ) from exc

    logger.info(
        "admin.user.created",
        target_user_id=record.user_id,
        admin_user_id=admin.user_id,
        role=record.role,
    )
    return _to_admin_user_item(record)


@router.patch("/users/{user_id}", response_model=AdminUserListItem)
async def update_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    admin: Annotated[UserRecord, Depends(require_admin)],
    user_store: Annotated[object, Depends(get_user_store_from_request)],
) -> AdminUserListItem:
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
        if user_id == admin.user_id and request.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin cannot disable their own account",
            )
        updated = user_store.set_active(user_id, request.is_active)
    if request.role is not None:
        if user_id == admin.user_id and request.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin cannot remove their own admin role",
            )
        updated = user_store.set_role(user_id, request.role) or updated
    if request.new_password:
        auth = get_auth_service()
        updated = user_store.update_password(
            user_id,
            auth.hash_password(request.new_password),
        ) or updated
    if request.email is not None or request.display_name is not None:
        current = user_store.get_by_id(user_id)
        if current is None:
            raise HTTPException(status_code=404, detail="User not found")
        updated = user_store.update_profile(
            user_id,
            email=(
                request.email if request.email is not None else current.email,
            ),
            display_name=(
                request.display_name
                if request.display_name is not None
                else current.display_name
            ),
        ) or updated

    record = user_store.get_by_id(user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(
        "admin.user.updated",
        target_user_id=user_id,
        admin_user_id=admin.user_id,
        is_active=request.is_active,
    )

    return _to_admin_user_item(record)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    admin: Annotated[UserRecord, Depends(require_admin)],
    user_store: Annotated[object, Depends(get_user_store_from_request)],
) -> None:
    """Delete a local user account."""
    if user_id == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin cannot delete their own account",
        )
    SessionManager.instance().close_sessions_for_user(user_id)
    if not user_store.delete_user(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info(
        "admin.user.deleted",
        target_user_id=user_id,
        admin_user_id=admin.user_id,
    )


@router.post("/users/sync-ad", response_model=AdminSyncADResponse)
async def sync_ad_users(
    admin: Annotated[UserRecord, Depends(require_admin)],
) -> AdminSyncADResponse:
    """Synchronize AD users.

    Local pilot mode has no directory connector configured, so this endpoint
    returns a no-op result while keeping the admin UI predictable.
    """
    logger.info("admin.users.sync_ad.noop", admin_user_id=admin.user_id)
    return AdminSyncADResponse()


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

    reply = request.reply or request.admin_reply
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reply text is required",
        )
    updated = feedback_store.reply(
        feedback_id=feedback_id,
        admin_user_id=admin.user_id,
        reply=reply,
        new_status=request.new_status or request.status,
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


@router.get("/analytics", response_model=AdminAnalyticsResponse)
async def get_analytics_dashboard(
    request: Request,
    admin: Annotated[UserRecord, Depends(require_admin)],
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AdminAnalyticsResponse:
    """Frontend dashboard analytics endpoint backed by local stores."""
    start_dt, end_dt = _parse_admin_range(from_date, to_date, days)
    sm = SessionManager.instance()
    rows = sm.store.list_sessions(user_id=None) if sm.store is not None else []
    rows_in_range = [
        row for row in rows
        if start_dt <= _parse_iso_dt(row["created_at"]) <= end_dt
    ]

    sessions_by_day: dict[str, int] = {}
    cursor = start_dt.date()
    while cursor <= end_dt.date():
        sessions_by_day[cursor.isoformat()] = 0
        cursor += timedelta(days=1)

    entity_counts: dict[str, int] = {}
    active_since = datetime.now(UTC) - timedelta(days=7)
    active_users: set[str] = set()
    for row in rows_in_range:
        created = _parse_iso_dt(row["created_at"])
        sessions_by_day[created.date().isoformat()] = (
            sessions_by_day.get(created.date().isoformat(), 0) + 1
        )
        user_id = row.get("user_id")
        if user_id and created >= active_since:
            active_users.add(user_id)
        entities_json = row.get("entities_json")
        if entities_json:
            try:
                for item in json.loads(entities_json):
                    entity_type = item.get("entity_type")
                    if entity_type:
                        entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
            except (TypeError, json.JSONDecodeError):
                logger.warning(
                    "admin.analytics.entities_json_failed",
                    session_id=row.get("session_id"),
                    exc_info=True,
                )

    latencies: list[float] = []
    error_rate_percent = 0.0
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        events = await audit_log.query(from_dt=start_dt, to_dt=end_dt, limit=20_000)
        http_events = [
            event for event in events
            if isinstance(event.get("payload"), dict)
            and event["payload"].get("status_code") is not None
        ]
        for event in http_events:
            if event.get("event_type") == "anonymize.done":
                latency = event["payload"].get("latency_ms")
                if isinstance(latency, (int, float)):
                    latencies.append(float(latency))
        if http_events:
            error_events = [
                event for event in http_events
                if int(event["payload"].get("status_code", 200)) >= 400
            ]
            error_rate_percent = round(len(error_events) / len(http_events) * 100, 2)

    logger.info(
        "admin.analytics_dashboard.queried",
        admin_id=admin.user_id,
        from_date=from_date,
        to_date=to_date,
        days=days,
        total_sessions=len(rows_in_range),
    )
    return AdminAnalyticsResponse(
        total_sessions=len(rows_in_range),
        anonymize_latency={
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "p99_ms": _percentile(latencies, 0.99),
        },
        sessions_per_day=[
            {"date": key, "count": value}
            for key, value in sorted(sessions_by_day.items())
        ],
        top_entity_types=[
            {"type": key, "count": value}
            for key, value in sorted(
                entity_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        active_users_7d=len(active_users),
        error_rate_percent=error_rate_percent,
    )
