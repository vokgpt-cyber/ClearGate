"""Session management endpoints.

Sprint B.3: every endpoint requires an authenticated user (via
``get_current_user``).  The authenticated ``user_id`` is threaded into
every SessionManager call so users can only see/mutate their own
sessions; cross-user access returns 404 (same as missing session) so
nothing leaks about the existence of other users\' data.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.api import CreateSessionRequest, CreateSessionResponse, SessionInfoResponse
from app.routers.auth import get_current_user
from app.services.session_manager import SessionManager
from app.services.user_store import UserRecord

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_session_manager() -> SessionManager:
    """Dependency: get the singleton SessionManager."""
    return SessionManager.instance()


@router.get("")
async def list_sessions(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> list:
    """List the authenticated user\'s persisted sessions (metadata only)."""
    return sm.list_sessions(user_id=current_user.user_id)


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> CreateSessionResponse:
    """Create a new anonymization session owned by the authenticated user."""
    session = sm.create_session(
        user_id=current_user.user_id,
        locale=request.locale,
        enable_llm_layer=request.enable_llm_layer,
        custom_entities=request.custom_entities,
    )
    expires_at = session.created_at + timedelta(minutes=1440)
    return CreateSessionResponse(
        session_id=session.session_id,
        created_at=session.created_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )


@router.get("/{session_id}", response_model=SessionInfoResponse)
async def get_session(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionInfoResponse:
    """Get session state (without exposing mapping table).

    Returns 404 both when the session is missing *and* when it belongs
    to another user -- the caller cannot tell the two cases apart.
    """
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfoResponse(
        session_id=session_id,
        created_at=session.created_at.isoformat(),
        entity_count=session.registry.entity_count,
        locale=session.locale,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_session(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> None:
    """Close session and securely clear all data.

    Silent no-op for sessions the caller does not own (SessionManager
    handles the ownership check) so a probe cannot distinguish "missing"
    from "someone else\'s session".
    """
    sm.close_session(session_id, user_id=current_user.user_id)
