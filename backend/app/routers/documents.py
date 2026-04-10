"""Document upload and parsing endpoints.

For DOCX uploads we additionally keep the raw bytes inside the session so
that the frontend can render the document with Word-like fidelity via
docx-preview (iteration 1 of the new anonymizer UX).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status

import structlog

from app.models.api import ParseTextRequest, UploadResponse
from app.services.doc_processor import DocumentProcessor
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
