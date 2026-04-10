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

from app.models.api import ParseTextRequest, UploadResponse
from app.services.doc_processor import DocumentProcessor
from app.services.docx_export import EntitySubstitution, export_anonymized_docx
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
            "rendering — the raw bytes are stored inside the session so the "
            "frontend can render the document with Word-like fidelity."
        ),
    ),
) -> UploadResponse:
    """Parse uploaded document (DOCX/PDF/TXT) and return plain text.

    For DOCX, if `session_id` is provided, the raw bytes are also stored
    in the session and can later be retrieved via
    `GET /api/documents/{session_id}/raw` for client-side rendering.
    """
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

    # For DOCX, attach raw bytes to the session for later client-side render.
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
    """Return the raw DOCX bytes stored for this session.

    Used by the frontend DocxViewer (docx-preview) to render the document
    with Word-like fidelity. Bytes are only served from memory — they are
    never written to disk and are wiped when the session is closed.
    """
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
    # HTTP header values are latin-1 in Starlette, so any non-ASCII
    # filename must be percent-encoded per RFC 5987. We also include a
    # sanitized ASCII `filename=` fallback for older clients. Without
    # encoding, Cyrillic filenames (e.g. "Тренировочный_Договор...docx")
    # trigger a UnicodeEncodeError when Starlette serializes headers and
    # surface on the client as a bare "Failed to fetch".
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
    """One entity from the frontend's in-memory workspace state.

    We only need `text`, `metadata.placeholder`, and `state` from the
    full ``InteractiveEntity`` on the client. Everything else (offsets,
    source_layer, score) is irrelevant for export because the naive
    per-run replacement doesn't care about offsets — it matches on the
    original text string.
    """

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
    """Return the uploaded DOCX with every non-rejected entity replaced.

    The session must have a DOCX previously attached via
    ``POST /api/documents/upload?session_id=...``. Rejected entities
    are skipped so the exported file matches exactly what the user sees
    in the right-hand pane.
    """
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
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("document.export_failed", session_id=session_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail="Failed to export anonymized DOCX",
        ) from exc

    # Derive a sensible download filename from the original.
    original = session.docx_filename or "document.docx"
    stem = original[:-5] if original.lower().endswith(".docx") else original
    download_name = f"{stem}_anonymized.docx"

    # RFC 5987 header for Cyrillic filenames — mirrors the /raw route.
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
