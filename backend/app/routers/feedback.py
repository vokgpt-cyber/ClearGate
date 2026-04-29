"""Public feedback endpoints: submit and retrieve user's own feedback."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user
from app.services.user_store import UserRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


# -----------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------


class FeedbackSubmitRequest(BaseModel):
    """Request to submit new feedback from the lawyer's feedback widget."""

    category: str = Field(..., min_length=1, max_length=50)  # bug, suggestion, question
    text: str = Field(..., min_length=1, max_length=100_000)
    page_url: str | None = None
    session_id: str | None = None
    screenshot: str | None = None  # base64-encoded image data


class FeedbackSubmitResponse(BaseModel):
    """Response from feedback submission."""

    id: int
    created_at: str


class FeedbackItemResponse(BaseModel):
    """Single feedback item (with optional admin reply)."""

    id: int
    created_at: str
    category: str
    text: str
    page_url: str | None
    status: str
    admin_reply: str | None
    admin_reply_at: str | None


class FeedbackListResponse(BaseModel):
    """Response from GET /api/feedback/mine."""

    items: list[FeedbackItemResponse]
    count: int


# -----------------------------------------------------------------------
# DI
# -----------------------------------------------------------------------


def get_feedback_store_from_request():
    """Dependency stub -- overridden in main.py lifespan."""
    raise RuntimeError(
        "FeedbackStore dependency not wired up; check main.py lifespan initialisation"
    )


# -----------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------


@router.post("/", response_model=FeedbackSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    feedback_request: FeedbackSubmitRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    feedback_store: Annotated[object, Depends(get_feedback_store_from_request)],
    http_request: Request,
) -> FeedbackSubmitResponse:
    """Submit feedback from the floating button in the UI.

    Requires authentication. The feedback is stored and visible to admins.
    Users can see their own feedback and any admin replies via GET /api/feedback/mine.

    Args:
        feedback_request: Feedback content and metadata.
        current_user: Authenticated user (from cookie).
        feedback_store: FeedbackStore instance (injected via Depends).
        http_request: HTTP request object for extracting headers.

    Returns:
        Newly created feedback id and timestamp.
    """

    # Decode screenshot if provided (base64 -> bytes).
    screenshot_bytes = None
    if feedback_request.screenshot:
        import base64

        try:
            screenshot_bytes = base64.b64decode(feedback_request.screenshot)
        except Exception as e:
            logger.warning(
                "feedback.submit.screenshot_decode_failed",
                user_id=current_user.user_id,
                exc=str(e),
            )
            # Non-fatal; submit without the screenshot.

    # Insert into store.
    feedback_id = feedback_store.submit(
        user_id=current_user.user_id,
        username=current_user.username,
        category=feedback_request.category,
        text=feedback_request.text,
        page_url=feedback_request.page_url,
        session_id=feedback_request.session_id,
        user_agent=http_request.headers.get("user-agent"),
        screenshot=screenshot_bytes,
    )

    # Fetch the created record to get created_at.
    record = feedback_store.get_by_id(feedback_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created feedback",
        )

    logger.info(
        "feedback.created",
        feedback_id=feedback_id,
        user_id=current_user.user_id,
        category=feedback_request.category,
    )

    return FeedbackSubmitResponse(id=feedback_id, created_at=record.created_at)


@router.get("/mine", response_model=FeedbackListResponse)
async def list_user_feedback(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    feedback_store: Annotated[object, Depends(get_feedback_store_from_request)],
) -> FeedbackListResponse:
    """Retrieve all feedback submitted by the current user, including admin replies.

    Used by the frontend feedback widget to display the user's own tickets.

    Args:
        current_user: Authenticated user.
        feedback_store: FeedbackStore instance (injected via Depends).

    Returns:
        List of feedback items ordered newest first.
    """

    records = feedback_store.list_for_user(current_user.user_id, limit=50)
    items = [
        FeedbackItemResponse(
            id=record.id,
            created_at=record.created_at,
            category=record.category,
            text=record.text,
            page_url=record.page_url,
            status=record.status,
            admin_reply=record.admin_reply,
            admin_reply_at=record.admin_reply_at,
        )
        for record in records
    ]

    logger.debug(
        "feedback.list_user",
        user_id=current_user.user_id,
        count=len(items),
    )

    return FeedbackListResponse(items=items, count=len(items))
