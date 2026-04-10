"""Anonymization and entity management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import structlog

from app.models.api import (
    AnonymizeRequest,
    AnonymizeResponse,
    DeanonymizeRequest,
    DeanonymizeResponse,
)
from app.services.session_manager import SessionManager
from app.routers.sessions import get_session_manager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["anonymize"])


@router.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(
    session_id: str,
    request: AnonymizeRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> AnonymizeResponse:
    """Run NER pipeline and return anonymized text with detected entities."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info("anonymize.start", session_id=session_id, text_length=len(request.text))

    entities = await session.pipeline.analyze(
        text=request.text,
        language=session.locale,
        custom_gliner_labels=session.custom_entities or None,
    )
    anonymized = session.registry.anonymize_text(request.text, entities)

    stats: dict[str, int] = {}
    for e in entities:
        stats[e.entity_type] = stats.get(e.entity_type, 0) + 1

    logger.info(
        "anonymize.done",
        session_id=session_id,
        entity_count=len(entities),
        stats=stats,
    )

    return AnonymizeResponse(
        anonymized_text=anonymized,
        entities=entities,
        stats=stats,
    )


@router.post("/deanonymize", response_model=DeanonymizeResponse)
async def deanonymize(
    session_id: str,
    request: DeanonymizeRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> DeanonymizeResponse:
    """Replace placeholders in text with original values."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return DeanonymizeResponse(text=session.registry.deanonymize_text(request.text))


@router.post("/llm")
async def send_to_llm(
    session_id: str,
    request: DeanonymizeRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> dict:
    """Send anonymized text to Cloud LLM and return deanonymized response.

    This is a synchronous (non-streaming) alternative to the WebSocket endpoint.
    The request.text should contain the prompt + anonymized document.
    """
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info("llm.send.start", session_id=session_id, text_length=len(request.text))

    try:
        from app.services.llm_adapters.claude import ClaudeAdapter

        adapter = ClaudeAdapter()
        chunks = []
        async for chunk in adapter.generate(
            anonymized_text=request.text,
            prompt="",
            model="claude-sonnet-4-6",
            thinking_level="high",
        ):
            if chunk.type == "text":
                chunks.append(chunk.content)
            elif chunk.type == "error":
                raise HTTPException(status_code=502, detail=chunk.content)

        raw_response = "".join(chunks)
        deanonymized = session.registry.deanonymize_text(raw_response)

        logger.info("llm.send.done", session_id=session_id)
        return {"response": deanonymized, "raw_length": len(raw_response)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("llm.send.error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"LLM request failed: {type(e).__name__}: {e}",
        )


@router.get("/entities")
async def get_entities(
    session_id: str,
    sm: SessionManager = Depends(get_session_manager),
) -> dict:
    """Get all detected entities for this session."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    entries = session.registry.get_all_entries()
    return {"entities": [e.model_dump() for e in entries]}
