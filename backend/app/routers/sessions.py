"""Session management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.api import CreateSessionRequest, CreateSessionResponse, SessionInfoResponse
from app.services.session_manager import SessionManager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_session_manager() -> SessionManager:
    """Dependency: get the singleton SessionManager."""
    return SessionManager.instance()


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> CreateSessionResponse:
    """Create a new anonymization session."""
    session = sm.create_session(
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
    sm: SessionManager = Depends(get_session_manager),
) -> SessionInfoResponse:
    """Get session state (without exposing mapping table)."""
    session = sm.get_session(session_id)
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
    sm: SessionManager = Depends(get_session_manager),
) -> None:
    """Close session and securely clear all data."""
    sm.close_session(session_id)
