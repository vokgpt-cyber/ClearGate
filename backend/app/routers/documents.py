"""Document upload and parsing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, status

import structlog

from app.models.api import ParseTextRequest, UploadResponse
from app.services.doc_processor import DocumentProcessor

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_SUPPORTED_FORMATS = {"docx", "pdf", "txt"}


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile) -> UploadResponse:
    """Parse uploaded document (DOCX/PDF/TXT) and return plain text."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = file.filename.lower().rsplit(".", maxsplit=1)[-1]
    if suffix not in _SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format: {suffix}. Supported: {', '.join(_SUPPORTED_FORMATS)}",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    processor = DocumentProcessor()
    result = processor.parse(content, format=suffix)

    logger.info(
        "document.uploaded",
        format=suffix,
        char_count=len(result.text),
        page_count=result.page_count,
    )

    return UploadResponse(
        text=result.text,
        format=suffix,
        page_count=result.page_count,
        char_count=len(result.text),
    )


@router.post("/parse-text", response_model=UploadResponse)
async def parse_text(request: ParseTextRequest) -> UploadResponse:
    """Accept plain text directly (no file upload needed)."""
    return UploadResponse(
        text=request.text,
        format="txt",
        char_count=len(request.text),
    )
