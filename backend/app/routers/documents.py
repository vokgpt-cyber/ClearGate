"""Document upload and parsing endpoints.

For DOCX uploads we additionally keep the raw bytes inside the session so
that the frontend can render the document with Word-like fidelity via
docx-preview (iteration 1 of the new anonymizer UX).

Sprint B.3: every session-scoped endpoint requires an authenticated user
and looks up / mutates only sessions owned by that user.  Cross-user
access returns 404 indistinguishably from a missing session.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

import structlog

from app.models.api import (
    DeanonymizeDocxResult,
    DocumentWorkflowState,
    ExportDeanonymizedRequest,
    ImportResponseResult,
    ManualResolution,
    ParseTextRequest,
    Restoration,
    UnresolvedPlaceholder,
    UploadResponse,
    WorkflowStageRequest,
)
from app.routers.auth import get_current_user
from app.routers.sessions import get_session_manager
from app.services.doc_processor import DocumentProcessor, ParseResult
from app.services.docx_deanonymize import deanonymize_docx, scan_placeholders
from app.services.docx_export import EntitySubstitution, export_anonymized_docx
from app.services.docx_utils import copy_page_setup
from app.services.session_manager import SessionManager
from app.services.user_store import UserRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_SUPPORTED_FORMATS = {"docx", "pdf", "txt"}

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _download_stem(filename: str | None, fallback: str = "document") -> str:
    if not filename:
        return fallback
    stem = Path(filename).stem
    return stem or fallback


def _bundle_filename(filenames: list[str]) -> str:
    """Human-readable filename for a multi-file session bundle."""
    clean = [name for name in filenames if name]
    if not clean:
        return "Пакет документов.docx"
    if len(clean) == 1:
        return (
            clean[0]
            if clean[0].lower().endswith(".docx")
            else f"{_download_stem(clean[0])}.docx"
        )
    first = _download_stem(clean[0])
    suffix = "файл" if len(clean) == 2 else "файла"
    return f"{first} + {len(clean) - 1} {suffix}.docx"


async def _parse_upload_part(
    file: UploadFile,
    processor: DocumentProcessor,
) -> tuple[str, str, int, ParseResult]:
    """Validate and parse one uploaded file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = file.filename.lower().rsplit(".", maxsplit=1)[-1]
    if suffix not in _SUPPORTED_FORMATS:
        supported = ", ".join(sorted(_SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format: {suffix}. Supported: {supported}",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    return suffix, file.filename, len(content), processor.parse(content, format=suffix)


def _reset_document_workflow(session) -> None:  # type: ignore[no-untyped-def]
    """Clear derived state after replacing/appending source documents."""
    session.response_docx_bytes = None
    session.response_docx_filename = None
    session.deanonymized_docx_bytes = None
    session.deanonymize_result_json = None
    session.manual_resolutions_json = None
    session.workflow_stage = "anonymized"
    session.anonymized_text = None
    session.detected_entities.clear()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    session_id: str | None = Query(
        default=None,
        description=(
            "Optional session to attach the document to. Required for DOCX "
            "rendering -- the raw bytes are stored inside the session so the "
            "frontend can render the document with Word-like fidelity."
        ),
    ),
) -> UploadResponse:
    """Parse uploaded document (DOCX/PDF/TXT) and return plain text."""
    processor = DocumentProcessor()
    suffix, filename, byte_count, result = await _parse_upload_part(file, processor)

    document_id: str | None = None
    if session_id is not None:
        session = sm.get_session(session_id, user_id=current_user.user_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found or expired",
            )
        render_bytes = result.render_docx_bytes
        if render_bytes is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document cannot be rendered as DOCX",
            )
        session.docx_bytes = render_bytes
        session.docx_filename = (
            filename
            if suffix == "docx"
            else f"{_download_stem(filename)}.docx"
        )
        session.source_format = suffix
        session.source_filename = filename
        _reset_document_workflow(session)
        document_id = session_id
        sm.save_session(session_id, user_id=current_user.user_id)
        logger.info(
            "document.attached_to_session",
            session_id=session_id,
            filename=filename,
            source_format=suffix,
            bytes=byte_count,
        )

    logger.info(
        "document.uploaded",
        format=suffix,
        char_count=len(result.text),
        page_count=result.page_count,
        attached=document_id is not None,
    )

    return UploadResponse(
        text=result.text,
        format=suffix,
        page_count=result.page_count,
        char_count=len(result.text),
        document_id=document_id,
    )


@router.post("/upload-batch", response_model=UploadResponse)
async def upload_document_batch(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    files: list[UploadFile] = File(...),
    session_id: str | None = Query(default=None),
    mode: Literal["replace", "append"] = Query(default="replace"),
) -> UploadResponse:
    """Parse and combine multiple DOCX/PDF/TXT files into one session document."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    processor = DocumentProcessor()
    session = None
    existing_names: list[str] = []
    results: list[ParseResult] = []

    if session_id is not None:
        session = sm.get_session(session_id, user_id=current_user.user_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found or expired",
            )
        if mode == "append" and session.docx_bytes is not None:
            results.append(processor.parse(session.docx_bytes, format="docx"))
            existing_names.append(session.source_filename or session.docx_filename or "document.docx")

    filenames: list[str] = []
    formats: list[str] = []
    total_bytes = 0
    for file in files:
        suffix, filename, byte_count, result = await _parse_upload_part(file, processor)
        filenames.append(filename)
        formats.append(suffix)
        total_bytes += byte_count
        results.append(result)

    combined = processor.combine_results(results)
    all_names = [*existing_names, *filenames]
    bundle_name = _bundle_filename(all_names)

    document_id: str | None = None
    if session is not None:
        if combined.render_docx_bytes is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Documents cannot be rendered as DOCX",
            )
        session.docx_bytes = combined.render_docx_bytes
        session.docx_filename = bundle_name
        session.source_format = formats[0] if len(set(formats)) == 1 and not existing_names else "batch"
        session.source_filename = bundle_name
        _reset_document_workflow(session)
        document_id = session_id
        sm.save_session(session_id, user_id=current_user.user_id)
        logger.info(
            "document.batch_attached_to_session",
            session_id=session_id,
            files=len(files),
            mode=mode,
            bytes=total_bytes,
        )

    return UploadResponse(
        text=combined.text,
        format="docx",
        page_count=combined.page_count,
        char_count=len(combined.text),
        document_id=document_id,
    )


@router.get("/{session_id}/raw")
async def get_raw_document(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> Response:
    """Return the raw DOCX bytes stored for this session."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )
    if session.docx_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No document attached to this session",
        )

    filename = session.docx_filename or "document.docx"
    ascii_fallback = filename.encode("ascii", errors="ignore").decode("ascii") or "document.docx"
    encoded = quote(filename, safe="")
    disposition = f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
    return Response(
        content=session.docx_bytes,
        media_type=_DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )


@router.post("/parse-text", response_model=UploadResponse)
async def parse_text(
    request: ParseTextRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> UploadResponse:
    """Accept plain text directly (no file upload needed).

    Auth-gated like every other /api/documents endpoint -- we do not want
    an anonymous caller using the backend as a free NLP endpoint.
    """
    return UploadResponse(
        text=request.text,
        format="txt",
        char_count=len(request.text),
    )


class _ExportEntity(BaseModel):
    """One entity from the frontend workspace state."""

    text: str
    placeholder: str = ""
    state: str = "pending"


class ExportAnonymizedRequest(BaseModel):
    """Body for the anonymized-DOCX export endpoint."""

    entities: list[_ExportEntity] = Field(default_factory=list)


@router.post("/{session_id}/export-anonymized")
async def export_anonymized(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    payload: ExportAnonymizedRequest = Body(...),
) -> Response:
    """Return the uploaded DOCX with every non-rejected entity replaced."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )
    if session.docx_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No DOCX attached to this session",
        )

    subs: list[EntitySubstitution] = [
        EntitySubstitution(text=e.text, placeholder=e.placeholder)
        for e in payload.entities
        if e.state != "rejected" and e.text and e.placeholder
    ]

    # BUG-P2-2 Layer 2: record per-occurrence surface forms in document
    # order so deanonymize_docx can restore the correct inflection for
    # each placeholder occurrence.  The frontend sends entities roughly
    # in document order (sorted by detection start offset).
    session.registry.record_surface_forms(
        [(s.text, s.placeholder) for s in subs]
    )
    sm.save_session(session_id, user_id=current_user.user_id)

    try:
        output_bytes = export_anonymized_docx(session.docx_bytes, subs)
    except Exception as exc:
        logger.error("document.export_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Failed to export anonymized DOCX",
        ) from exc

    original = getattr(session, "source_filename", None) or session.docx_filename
    stem = _download_stem(original)
    download_name = f"ANON_{stem}.docx"

    from urllib.parse import quote as _quote

    ascii_fallback = (
        download_name.encode("ascii", errors="ignore").decode("ascii")
        or "document_anonymized.docx"
    )
    encoded = _quote(download_name, safe="")
    disposition = (
        f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
    )

    logger.info(
        "document.exported",
        session_id=session_id,
        input_entities=len(payload.entities),
        applied_subs=len(subs),
        output_bytes=len(output_bytes),
    )

    return Response(
        content=output_bytes,
        media_type=_DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )


# -- Phase 1 round-trip: import response, deanonymize, export -----------


@router.get("/{session_id}/response-raw")
async def get_response_raw(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> Response:
    """Return the deanonymized DOCX bytes for client-side preview."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )

    docx_bytes = getattr(session, "deanonymized_docx_bytes", None)
    if docx_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deanonymized document available for this session",
        )

    filename = getattr(session, "source_filename", None) or session.docx_filename
    stem = _download_stem(filename)
    download_name = f"DEAN_{stem}.docx"

    ascii_fallback = (
        download_name.encode("ascii", errors="ignore").decode("ascii")
        or "document_deanonymized.docx"
    )
    encoded = quote(download_name, safe="")
    disposition = f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'

    return Response(
        content=docx_bytes,
        media_type=_DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )


@router.post("/{session_id}/import-response", response_model=ImportResponseResult)
async def import_response(
    session_id: str,
    file: UploadFile,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> ImportResponseResult:
    """Import an LLM-response DOCX for deanonymization."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    processor = DocumentProcessor()
    result = processor.parse(content, format="docx")

    # Transplant page geometry from the original DOCX so the deanonymized
    # preview renders with the same margins/page size as the left pane.
    original = getattr(session, "docx_bytes", None)
    if original:
        content = copy_page_setup(original, content)

    session.response_docx_bytes = content
    session.response_docx_filename = file.filename
    session.deanonymized_docx_bytes = None
    session.deanonymize_result_json = None
    session.manual_resolutions_json = None
    session.workflow_stage = "llm_response"
    sm.save_session(session_id, user_id=current_user.user_id)

    placeholders = scan_placeholders(result.text)

    logger.info(
        "document.response_imported",
        session_id=session_id,
        char_count=len(result.text),
        placeholder_count=len(placeholders),
    )

    return ImportResponseResult(
        text=result.text,
        char_count=len(result.text),
        placeholder_count=len(placeholders),
    )


def _stored_deanonymize_result(session) -> DeanonymizeDocxResult | None:  # type: ignore[no-untyped-def]
    raw = getattr(session, "deanonymize_result_json", None)
    if not raw:
        return None
    try:
        return DeanonymizeDocxResult.model_validate_json(raw)
    except Exception:
        logger.warning(
            "document.workflow_result_invalid",
            session_id=getattr(session, "session_id", None),
            exc_info=True,
        )
        return None


def _stored_manual_resolutions(session) -> list[ManualResolution]:  # type: ignore[no-untyped-def]
    raw = getattr(session, "manual_resolutions_json", None)
    if not raw:
        return []
    try:
        values = json.loads(raw)
        if not isinstance(values, list):
            return []
        return [ManualResolution.model_validate(item) for item in values]
    except Exception:
        logger.warning(
            "document.workflow_manual_resolutions_invalid",
            session_id=getattr(session, "session_id", None),
            exc_info=True,
        )
        return []


@router.get("/{session_id}/workflow", response_model=DocumentWorkflowState)
async def get_workflow_state(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> DocumentWorkflowState:
    """Return persisted LLM-response/deanonymization workflow state."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )

    response_imported = getattr(session, "response_docx_bytes", None) is not None
    deanonymized_available = getattr(session, "deanonymized_docx_bytes", None) is not None
    stage = getattr(session, "workflow_stage", "anonymized") or "anonymized"
    if stage == "deanonymized" and not deanonymized_available:
        stage = "llm_response" if response_imported else "anonymized"
    if stage == "llm_response" and not response_imported:
        stage = "anonymized"

    return DocumentWorkflowState(
        stage=stage,
        response_imported=response_imported,
        deanonymized_available=deanonymized_available,
        response_docx_filename=getattr(session, "response_docx_filename", None),
        deanonymize_result=_stored_deanonymize_result(session),
        manual_resolutions=_stored_manual_resolutions(session),
    )


@router.post("/{session_id}/workflow-stage", response_model=DocumentWorkflowState)
async def set_workflow_stage(
    session_id: str,
    payload: WorkflowStageRequest,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> DocumentWorkflowState:
    """Persist which workflow stage the user is currently viewing."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )
    if payload.stage in {"llm_response", "deanonymized"} and getattr(
        session, "response_docx_bytes", None
    ) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No response DOCX imported for this session",
        )
    if payload.stage == "deanonymized" and getattr(
        session, "deanonymized_docx_bytes", None
    ) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No deanonymized DOCX available for this session",
        )

    session.workflow_stage = payload.stage
    sm.save_session(session_id, user_id=current_user.user_id)
    return await get_workflow_state(session_id, current_user, sm)


class DeanonymizeRequest(BaseModel):
    """Optional body for the deanonymize endpoint."""

    manual_resolutions: list[dict] = Field(
        default_factory=list,
        description="List of {placeholder, value} pairs for unresolved placeholders",
    )


@router.post("/{session_id}/deanonymize-docx", response_model=DeanonymizeDocxResult)
async def deanonymize_docx_endpoint(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    payload: DeanonymizeRequest = Body(default=DeanonymizeRequest()),
) -> DeanonymizeDocxResult:
    """Deanonymize the previously imported response DOCX."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )

    response_bytes = getattr(session, "response_docx_bytes", None)
    if response_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No response DOCX imported for this session",
        )

    if session.registry is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session has no entity registry -- anonymize first",
        )

    manual: dict[str, str] = {}
    for res in payload.manual_resolutions:
        ph = res.get("placeholder", "")
        val = res.get("value", "")
        if ph and val:
            manual[ph] = val

    try:
        result = deanonymize_docx(response_bytes, session.registry, manual or None)
    except Exception as exc:
        logger.error("document.deanonymize_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Deanonymization failed") from exc

    unresolved = [
        UnresolvedPlaceholder(
            raw_text=m.raw_text,
            normalized=m.normalized,
            paragraph_index=m.paragraph_index,
        )
        for m in result.unresolved
    ]

    # Build restoration list with entity_type resolved from the registry so
    # the frontend can apply the matching overlay color/style per type.
    restorations: list[Restoration] = []
    reverse = session.registry._reverse  # placeholder -> MappingEntry
    for m in result.replacements:
        if m.real_value is None:
            continue
        entry = reverse.get(m.normalized)
        entity_type = entry.entity_type if entry is not None else "CUSTOM"
        restorations.append(
            Restoration(
                placeholder=m.normalized,
                real_value=m.real_value,
                entity_type=entity_type,
                paragraph_index=m.paragraph_index,
            )
        )

    response_model = DeanonymizeDocxResult(
        unresolved=unresolved,
        restorations=restorations,
        total_replacements=len(result.replacements),
        total_unresolved=len(unresolved),
    )
    session.deanonymized_docx_bytes = result.docx_bytes
    session.deanonymize_result_json = response_model.model_dump_json()
    session.manual_resolutions_json = json.dumps(
        [r.model_dump() for r in payload.manual_resolutions],
        ensure_ascii=False,
    )
    session.workflow_stage = "deanonymized"
    sm.save_session(session_id, user_id=current_user.user_id)

    logger.info(
        "document.deanonymized",
        session_id=session_id,
        replacements=len(result.replacements),
        unresolved=len(unresolved),
    )

    return response_model


@router.post("/{session_id}/export-deanonymized")
async def export_deanonymized(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    payload: ExportDeanonymizedRequest = Body(default=ExportDeanonymizedRequest()),
) -> Response:
    """Export the deanonymized DOCX, optionally applying manual resolutions."""
    session = sm.get_session(session_id, user_id=current_user.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or expired",
        )

    response_bytes = getattr(session, "response_docx_bytes", None)
    if response_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No response DOCX imported for this session",
        )

    if session.registry is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session has no entity registry -- anonymize first",
        )

    manual: dict[str, str] = {}
    for res in payload.manual_resolutions:
        manual[res.placeholder] = res.value

    try:
        result = deanonymize_docx(response_bytes, session.registry, manual)
    except Exception as exc:
        logger.error("document.deanonymize_export_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Deanonymization export failed") from exc

    unresolved = [
        UnresolvedPlaceholder(
            raw_text=m.raw_text,
            normalized=m.normalized,
            paragraph_index=m.paragraph_index,
        )
        for m in result.unresolved
    ]
    restorations: list[Restoration] = []
    reverse = session.registry._reverse
    for m in result.replacements:
        if m.real_value is None:
            continue
        entry = reverse.get(m.normalized)
        restorations.append(
            Restoration(
                placeholder=m.normalized,
                real_value=m.real_value,
                entity_type=entry.entity_type if entry is not None else "CUSTOM",
                paragraph_index=m.paragraph_index,
            )
        )
    response_model = DeanonymizeDocxResult(
        unresolved=unresolved,
        restorations=restorations,
        total_replacements=len(result.replacements),
        total_unresolved=len(unresolved),
    )
    session.deanonymized_docx_bytes = result.docx_bytes
    session.deanonymize_result_json = response_model.model_dump_json()
    session.manual_resolutions_json = json.dumps(
        [r.model_dump() for r in payload.manual_resolutions],
        ensure_ascii=False,
    )
    session.workflow_stage = "deanonymized"
    sm.save_session(session_id, user_id=current_user.user_id)

    original = getattr(session, "source_filename", None) or session.docx_filename
    stem = _download_stem(original)
    download_name = f"DEAN_{stem}.docx"

    ascii_fallback = (
        download_name.encode("ascii", errors="ignore").decode("ascii")
        or "document_deanonymized.docx"
    )
    encoded = quote(download_name, safe="")
    disposition = (
        f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
    )

    logger.info(
        "document.deanonymized_exported",
        session_id=session_id,
        replacements=len(result.replacements),
        unresolved=len(result.unresolved),
        manual_resolutions=len(manual),
    )

    return Response(
        content=result.docx_bytes,
        media_type=_DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )
