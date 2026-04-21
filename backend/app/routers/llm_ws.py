"""WebSocket endpoint for streaming LLM responses.

Accepts a JSON request with session_id, anonymized text, prompt,
provider, and model. Streams thinking and text deltas, then sends
a final message with the deanonymized response.

Sprint B.3: WebSockets cannot use the usual ``Depends(get_current_user)``
dependency cleanly, so auth happens manually during the handshake:
we read the ``cg_session`` cookie, verify it against the configured
``AuthService`` + ``UserStore``, and look up a ``UserRecord``.  If any
step fails, we close with code 1008 (policy violation) *before*
accepting app-level messages.  All session lookups are then scoped to
that user\'s ``user_id``.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.routers.auth import _resolve_user_from_cookie, get_user_store_from_request
from app.services.auth import get_auth_service
from app.services.llm_adapters.registry import get_adapter
from app.services.session_manager import SessionManager

logger = structlog.get_logger(__name__)

router = APIRouter()

# WebSocket close codes -- 1008 "policy violation" is what RFC 6455
# reserves for auth/authorization failures.
_CLOSE_POLICY_VIOLATION = 1008


class StreamRequest(BaseModel):
    """Incoming WebSocket request to start LLM streaming."""

    session_id: str
    anonymized_text: str
    prompt: str
    provider: Literal["claude", "openai", "gemini"] = "claude"
    model: str = "claude-sonnet-4-6"
    thinking_level: Literal["off", "low", "medium", "high", "max"] = "high"
    max_tokens: int = 8192


def _resolve_ws_user(websocket: WebSocket) -> str | None:
    """Resolve the authenticated user\'s ``user_id`` from the handshake cookie.

    Returns ``None`` if the cookie is missing / invalid / points at an
    inactive user.  Intentionally swallows *all* errors so a malformed
    UserStore DI override during tests doesn\'t surface on the wire as
    a stack trace -- the caller closes with 1008 either way.

    We reach into ``websocket.app.dependency_overrides`` directly instead
    of going through FastAPI\'s dependency system because ``Depends``
    only works inside HTTP route handlers; WebSocket handlers need to
    unpack the same state by hand.
    """
    cookie_value = websocket.cookies.get(settings.cleargate_auth_cookie_name)
    if not cookie_value:
        return None
    try:
        auth = get_auth_service()
    except RuntimeError:
        # AuthService not initialised -- should never happen at runtime
        # because ``main.py`` sets it up in ``lifespan``, but tests that
        # import this module without startup get a clean 1008.
        return None
    overrides = getattr(websocket.app, "dependency_overrides", {})
    users_factory = overrides.get(get_user_store_from_request)
    if users_factory is None:
        return None
    try:
        users = users_factory()
    except Exception:
        return None
    rec = _resolve_user_from_cookie(cookie_value, auth, users)
    return rec.user_id if rec is not None else None


@router.websocket("/ws/stream")
async def llm_stream(websocket: WebSocket) -> None:
    """Stream LLM response tokens over WebSocket.

    Protocol:
        1. Client presents ``cg_session`` cookie in the handshake
        2. Server accepts (or closes 1008 on auth failure)
        3. Client sends a JSON StreamRequest
        4. Server streams: thinking_delta, text_delta messages
        5. Server sends final message with deanonymized text
        6. Server closes connection
    """
    # Resolve auth BEFORE accepting so unauthenticated clients get a
    # proper handshake-level close rather than a successful upgrade
    # followed by an app-level error message.
    user_id = _resolve_ws_user(websocket)
    if user_id is None:
        await websocket.close(code=_CLOSE_POLICY_VIOLATION, reason="Not authenticated")
        logger.info("ws.stream.auth_failed")
        return

    await websocket.accept()
    sm = SessionManager.instance()

    try:
        raw = await websocket.receive_json()
        try:
            request = StreamRequest(**raw)
        except ValidationError as e:
            await websocket.send_json({"type": "error", "content": f"Invalid request: {e}"})
            await websocket.close()
            return

        session = sm.get_session(request.session_id, user_id=user_id)
        if not session:
            await websocket.send_json({"type": "error", "content": "Session not found"})
            await websocket.close()
            return

        try:
            adapter = get_adapter(request.provider)
        except ValueError as e:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.close()
            return

        logger.info(
            "ws.stream.start",
            session_id=request.session_id,
            user_id=user_id,
            provider=request.provider,
            model=request.model,
            thinking_level=request.thinking_level,
            text_length=len(request.anonymized_text),
        )

        accumulated_text = ""

        async for chunk in adapter.generate(
            anonymized_text=request.anonymized_text,
            prompt=request.prompt,
            model=request.model,
            thinking_level=request.thinking_level,
            max_tokens=request.max_tokens,
        ):
            if chunk.type == "thinking":
                await websocket.send_json({
                    "type": "thinking_delta",
                    "content": chunk.content,
                })
            elif chunk.type == "text":
                accumulated_text += chunk.content
                await websocket.send_json({
                    "type": "text_delta",
                    "content": chunk.content,
                })
            elif chunk.type == "done":
                deanonymized = session.registry.deanonymize_text(accumulated_text)
                await websocket.send_json({
                    "type": "final",
                    "content": deanonymized,
                    "metadata": chunk.metadata,
                })
            elif chunk.type == "error":
                await websocket.send_json({
                    "type": "error",
                    "content": chunk.content,
                })

        logger.info("ws.stream.done", session_id=request.session_id, user_id=user_id)
        await websocket.close()

    except WebSocketDisconnect:
        logger.info("ws.stream.disconnected", user_id=user_id)
    except Exception:
        logger.error("ws.stream.error", user_id=user_id, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "content": "Internal error"})
            await websocket.close()
        except Exception:
            pass
