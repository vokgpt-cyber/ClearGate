"""Document upload and parsing endpoints.

For DOCX uploads we additionally keep the raw bytes inside the session so
that the frontend can render the document with Word-like fidelity via
docx-preview (iteration 1 of the new anonymizer UX).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field

import structlog

from app.models.api import (
    DeanonymizeDocxResult,
    ExportDeanonymizedRequest,
    ImportResponseResult,
    ParseTextRequest,
    Restoration,
    UnresolvedPlaceholder,
    UploadResponse,
)
from app.services.doc_processor import DocumentProcessor
from app.services.docx_deanonymize import deanonymize_docx, scan_placeholders
from app.services.docx_export import EntitySubstitution, export_anonymized_docx
from app.services.docx_utils import copy_page_setup
from app.services.session_manager import SessionManager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_SUPPORTED_FORMATS = {"docx", "pdf", "txt"}

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
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

    processor = DocumentProcessor()
    result = processor.parse(content, format=suffix)

    document_id: str | None = None
    if suffix == "docx" and session_id is not None:
        manager = SessionManager.instance()
        session = manager.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found or expired",
            )
        session.docx_bytes = content
        session.docx_filename = file.filename
        document_id = session_id
        manager.save_session(session_id)
        logger.info(
            "document.attached_to_session",
            session_id=session_id,
            filename=file.filename,
            bytes=len(content),
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


@router.get("/{session_id}/raw")
async def get_raw_document(session_id: str) -> Response:
    """Return the raw DOCX bytes stored for this session."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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
async def parse_text(request: ParseTextRequest) -> UploadResponse:
    """Accept plain text directly (no file upload needed)."""
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
    payload: ExportAnonymizedRequest = Body(...),
) -> Response:
    """Return the uploaded DOCX with every non-rejected entity replaced."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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

    try:
        output_bytes = export_anonymized_docx(session.docx_bytes, subs)
    except Exception as exc:
        logger.error("document.export_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Failed to export anonymized DOCX",
        ) from exc

    original = session.docx_filename or "document.docx"
    stem = original[:-5] if original.lower().endswith(".docx") else original
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
async def get_response_raw(session_id: str) -> Response:
    """Return the deanonymized DOCX bytes for client-side preview."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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

    filename = session.docx_filename or "document.docx"
    stem = filename[:-5] if filename.lower().endswith(".docx") else filename
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
) -> ImportResponseResult:
    """Import an LLM-response DOCX for deanonymization."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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
    manager.save_session(session_id)

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


class DeanonymizeRequest(BaseModel):
    """Optional body for the deanonymize endpoint."""

    manual_resolutions: list[dict] = Field(
        default_factory=list,
        description="List of {placeholder, value} pairs for unresolved placeholders",
    )


@router.post("/{session_id}/deanonymize-docx", response_model=DeanonymizeDocxResult)
async def deanonymize_docx_endpoint(
    session_id: str,
    payload: DeanonymizeRequest = Body(default=DeanonymizeRequest()),
) -> DeanonymizeDocxResult:
    """Deanonymize the previously imported response DOCX."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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

    session.deanonymized_docx_bytes = result.docx_bytes
    manager.save_session(session_id)

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
    reverse = session.registry._reverse  # placeholder → MappingEntry
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

    logger.info(
        "document.deanonymized",
        session_id=session_id,
        replacements=len(result.replacements),
        unresolved=len(unresolved),
    )

    return DeanonymizeDocxResult(
        unresolved=unresolved,
        restorations=restorations,
        total_replacements=len(result.replacements),
        total_unresolved=len(unresolved),
    )


@router.post("/{session_id}/export-deanonymized")
async def export_deanonymized(
    session_id: str,
    payload: ExportDeanonymizedRequest = Body(default=ExportDeanonymizedRequest()),
) -> Response:
    """Export the deanonymized DOCX, optionally applying manual resolutions."""
    manager = SessionManager.instance()
    session = manager.get_session(session_id)
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

    session.deanonymized_docx_bytes = result.docx_bytes
    manager.save_session(session_id)

    original = session.docx_filename or "document.docx"
    stem = original[:-5] if original.lower().endswith(".docx") else original
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
