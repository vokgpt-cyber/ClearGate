"""Anonymization and entity management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

import structlog

from app.models.api import (
    AddEntityRequest,
    AddEntityResponse,
    AnonymizeRequest,
    AnonymizeResponse,
    DeanonymizeRequest,
    DeanonymizeResponse,
)
from app.models.entities import DetectedEntity
from app.services.session_manager import SessionManager
from app.routers.sessions import get_session_manager


def _stable_entity_id(entity: DetectedEntity) -> str:
    """Deterministic id for a detected entity.

    We intentionally keep this stable across repeated ``/anonymize`` calls
    on the same text + pipeline, so the frontend can diff state without
    losing accept/reject decisions if the user re-runs detection.
    """
    return f"det-{entity.source_layer}-{entity.start}-{entity.end}-{entity.entity_type}"

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

    # Attach the placeholder that the registry assigned to each entity so
    # the frontend can render the anonymized view (substituting ranges
    # with placeholders) without having to parse `anonymized_text` itself.
    # `get_or_create_placeholder` is idempotent — `anonymize_text` above
    # already created the entries, so these lookups are cheap hits.
    for e in entities:
        try:
            placeholder = session.registry.get_or_create_placeholder(e)
        except Exception:  # pragma: no cover — defensive
            placeholder = None
        if placeholder is not None:
            e.metadata["placeholder"] = placeholder
        # Stable id so the frontend can track accept/reject state across
        # re-detections without losing user decisions.
        e.metadata["id"] = _stable_entity_id(e)
        # Mark as pipeline-detected so the UI can distinguish from custom
        # user-added entities.
        e.metadata.setdefault("state", "pending")

    stats: dict[str, int] = {}
    for e in entities:
        stats[e.entity_type] = stats.get(e.entity_type, 0) + 1

    logger.info(
        "anonymize.done",
        session_id=session_id,
        entity_count=len(entities),
        stats=stats,
    )

    # Persist session state after registry mutation
    sm.save_session(session_id)

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


@router.post("/entities", response_model=AddEntityResponse)
async def add_entity(
    session_id: str,
    request: AddEntityRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> AddEntityResponse:
    """Manually register a custom entity selected by the user.

    Used by the UI "Add as entity" flow: user selects text in the left
    panel, picks a type from the popover, frontend POSTs here. We create
    a :class:`DetectedEntity`, register it in the session's
    :class:`EntityRegistry` (which assigns a consistent placeholder like
    the pipeline does), and hand back the id + placeholder so the client
    can render the new overlay immediately.

    The entity is NOT persisted on the backend — the source of truth for
    the set of currently-active entities is the frontend workspace state.
    This keeps the backend stateless per anonymization run and avoids
    having to reconcile state on reload (iteration 3 scope).
    """
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.end <= request.start:
        raise HTTPException(status_code=400, detail="end must be greater than start")

    entity = DetectedEntity(
        text=request.text,
        entity_type=request.entity_type,
        start=request.start,
        end=request.end,
        score=1.0,  # manually added = full confidence
        source_layer="regex",  # closest existing value; we tag via metadata
        metadata={"user_added": True, "state": "custom"},
    )

    try:
        placeholder = session.registry.get_or_create_placeholder(entity)
    except Exception as exc:
        logger.error("add_entity.placeholder_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to assign placeholder")

    entity_id = f"custom-{uuid.uuid4()}"
    entity.metadata["placeholder"] = placeholder
    entity.metadata["id"] = entity_id

    logger.info(
        "entity.added",
        session_id=session_id,
        entity_type=entity.entity_type,
        placeholder=placeholder,
    )

    # Persist after manual entity addition
    sm.save_session(session_id)

    return AddEntityResponse(id=entity_id, placeholder=placeholder, entity=entity)


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
