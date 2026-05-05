"""Anonymization and entity management endpoints.

Sprint B.3: every endpoint requires an authenticated user and scopes
session lookups/mutations by ``user_id``.  Cross-user access returns 404
indistinguishably from a missing session.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

import structlog

from app.models.api import (
    AddEntityRequest,
    AddEntityResponse,
    AnonymizeRequest,
    AnonymizeResponse,
    DeanonymizeRequest,
    DeanonymizeResponse,
    DeepScanRequest,
)
from app.models.entities import DetectedEntity
from app.routers.auth import get_current_user
from app.routers.sessions import get_session_manager
from app.config import settings
from app.services.local_llm_verifier import LocalLLMVerifier
from app.services.session_manager import SessionManager
from app.services.user_store import UserRecord


def _stable_entity_id(entity: DetectedEntity) -> str:
    """Deterministic id for a detected entity.

    We intentionally keep this stable across repeated ``/anonymize`` calls
    on the same text + pipeline, so the frontend can diff state without
    losing accept/reject decisions if the user re-runs detection.
    """
    return f"det-{entity.source_layer}-{entity.start}-{entity.end}-{entity.entity_type}"

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["anonymize"])


def _align_entity_to_text(text: str, entity: DetectedEntity) -> DetectedEntity | None:
    """Ensure an LLM-returned entity points to the actual source text."""
    if 0 <= entity.start < entity.end <= len(text) and text[entity.start : entity.end] == entity.text:
        return entity

    needle = entity.text.strip()
    if not needle:
        return None
    idx = text.find(needle)
    if idx < 0:
        return None
    return entity.model_copy(update={"start": idx, "end": idx + len(needle), "text": needle})


def _prepare_response_entities(
    session,
    entities: list[DetectedEntity],
    previous: list[DetectedEntity] | None = None,
) -> list[DetectedEntity]:
    """Attach stable ids/placeholders and preserve reviewed UI state when possible."""
    previous_by_key = {
        (e.start, e.end, e.entity_type, e.text): e
        for e in (previous or [])
    }
    prepared: list[DetectedEntity] = []
    for entity in entities:
        prior = previous_by_key.get((entity.start, entity.end, entity.entity_type, entity.text))
        metadata = dict(entity.metadata or {})
        if prior is not None:
            metadata.update({
                k: v
                for k, v in (prior.metadata or {}).items()
                if k in {"id", "placeholder", "state", "user_added"}
            })
        try:
            placeholder = session.registry.get_or_create_placeholder(entity)
        except Exception:  # pragma: no cover -- defensive
            placeholder = metadata.get("placeholder")
        if placeholder is not None:
            metadata["placeholder"] = placeholder
        metadata.setdefault("id", _stable_entity_id(entity))
        metadata.setdefault("state", "pending")
        prepared.append(entity.model_copy(update={"metadata": metadata}))
    return prepared


def _stats_for(entities: list[DetectedEntity]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for entity in entities:
        stats[entity.entity_type] = stats.get(entity.entity_type, 0) + 1
    return stats


@router.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(
    session_id: str,
    request: AnonymizeRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> AnonymizeResponse:
    """Run NER pipeline and return anonymized text with detected entities."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info("anonymize.start", session_id=session_id, text_length=len(request.text))

    entities = await session.pipeline.analyze(
        text=request.text,
        language=session.locale,
        custom_gliner_labels=session.custom_entities or None,
    )
    anonymized = session.registry.anonymize_text(request.text, entities)

    entities = _prepare_response_entities(session, entities)

    session.anonymized_text = anonymized
    session.detected_entities = entities

    stats = _stats_for(entities)

    logger.info(
        "anonymize.done",
        session_id=session_id,
        entity_count=len(entities),
        stats=stats,
    )

    # Persist session state after registry mutation
    sm.save_session(session_id, user_id=current_user.user_id)

    return AnonymizeResponse(
        anonymized_text=anonymized,
        entities=entities,
        stats=stats,
    )


@router.post("/deep-scan", response_model=AnonymizeResponse)
async def deep_scan(
    session_id: str,
    request: DeepScanRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> AnonymizeResponse:
    """Run optional local LLM verification over the current detection result."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(
        "deep_scan.start",
        session_id=session_id,
        text_length=len(request.text),
        input_entity_count=len(request.entities),
    )

    current_entities = request.entities or session.detected_entities
    custom_entities = [
        e for e in current_entities
        if (e.metadata or {}).get("state") == "custom"
    ]
    candidates = [
        e for e in current_entities
        if (e.metadata or {}).get("state") != "rejected"
    ]

    verifier = LocalLLMVerifier(
        model=settings.ollama_model,
        base_url=settings.ollama_host,
    )
    refined = await verifier.verify_and_refine(request.text, candidates) if candidates else []
    missed = await verifier.find_missed_entities(request.text, refined or candidates)

    aligned: list[DetectedEntity] = []
    # Deep scan is additive/conservative: keep the current non-rejected
    # detection set so the LLM cannot silently drop structured regex hits
    # such as contract numbers, dates, INN or amounts. Post-processing below
    # still removes known false positives like document-type titles and role
    # labels.
    for entity in [*candidates, *refined, *missed, *custom_entities]:
        fixed = _align_entity_to_text(request.text, entity)
        if fixed is not None:
            aligned.append(fixed)

    entities = session.pipeline.post_process(request.text, aligned)
    entities = _prepare_response_entities(session, entities, previous=current_entities)
    anonymized = session.registry.anonymize_text(request.text, entities)
    session.anonymized_text = anonymized
    session.detected_entities = entities

    stats = _stats_for(entities)
    logger.info(
        "deep_scan.done",
        session_id=session_id,
        entity_count=len(entities),
        stats=stats,
    )
    sm.save_session(session_id, user_id=current_user.user_id)

    return AnonymizeResponse(
        anonymized_text=anonymized,
        entities=entities,
        stats=stats,
    )


@router.post("/deanonymize", response_model=DeanonymizeResponse)
async def deanonymize(
    session_id: str,
    request: DeanonymizeRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> DeanonymizeResponse:
    """Replace placeholders in text with original values."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return DeanonymizeResponse(text=session.registry.deanonymize_text(request.text))


@router.post("/llm")
async def send_to_llm(
    session_id: str,
    request: DeanonymizeRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict:
    """Send anonymized text to Cloud LLM and return deanonymized response.

    This is a synchronous (non-streaming) alternative to the WebSocket endpoint.
    The request.text should contain the prompt + anonymized document.
    """
    session = sm.get_session(session_id, user_id=current_user.user_id)
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
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> AddEntityResponse:
    """Manually register a custom entity selected by the user.

    Used by the UI "Add as entity" flow: user selects text in the left
    panel, picks a type from the popover, frontend POSTs here. We create
    a :class:`DetectedEntity`, register it in the session\'s
    :class:`EntityRegistry` (which assigns a consistent placeholder like
    the pipeline does), and hand back the id + placeholder so the client
    can render the new overlay immediately.

    The entity is NOT persisted on the backend -- the source of truth for
    the set of currently-active entities is the frontend workspace state.
    This keeps the backend stateless per anonymization run and avoids
    having to reconcile state on reload (iteration 3 scope).
    """
    session = sm.get_session(session_id, user_id=current_user.user_id)
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
    current = getattr(session, "detected_entities", [])
    session.detected_entities = [
        e
        for e in current
        if not (e.start >= entity.start and e.end <= entity.end)
    ] + [entity]

    logger.info(
        "entity.added",
        session_id=session_id,
        entity_type=entity.entity_type,
        placeholder=placeholder,
    )

    # Persist after manual entity addition
    sm.save_session(session_id, user_id=current_user.user_id)

    return AddEntityResponse(id=entity_id, placeholder=placeholder, entity=entity)


@router.get("/entities")
async def get_entities(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict:
    """Get all detected entities for this session."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    entries = session.registry.get_all_entries()
    return {"entities": [e.model_dump() for e in entries]}
