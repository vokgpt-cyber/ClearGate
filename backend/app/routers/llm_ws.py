"""WebSocket endpoint for streaming LLM responses.

Accepts a JSON request with session_id, anonymized text, prompt,
provider, and model. Streams thinking and text deltas, then sends
a final message with the deanonymized response.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.services.llm_adapters.registry import get_adapter
from app.services.session_manager import SessionManager

logger = structlog.get_logger(__name__)

router = APIRouter()


class StreamRequest(BaseModel):
    """Incoming WebSocket request to start LLM streaming."""

    session_id: str
    anonymized_text: str
    prompt: str
    provider: Literal["claude", "openai", "gemini"] = "claude"
    model: str = "claude-sonnet-4-6"
    thinking_level: Literal["off", "low", "medium", "high", "max"] = "high"
    max_tokens: int = 8192


@router.websocket("/ws/stream")
async def llm_stream(websocket: WebSocket) -> None:
    """Stream LLM response tokens over WebSocket.

    Protocol:
        1. Client connects, sends a JSON StreamRequest
        2. Server streams: thinking_delta, text_delta messages
        3. Server sends final message with deanonymized text
        4. Server closes connection
    """
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

        session = sm.get_session(request.session_id)
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

        logger.info("ws.stream.done", session_id=request.session_id)
        await websocket.close()

    except WebSocketDisconnect:
        logger.info("ws.stream.disconnected")
    except Exception:
        logger.error("ws.stream.error", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "content": "Internal error"})
            await websocket.close()
        except Exception:
            pass
