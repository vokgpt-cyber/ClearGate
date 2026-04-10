"""Document parsing for DOCX, PDF, and TXT files.

Parses uploaded files into plain text in memory (no temp files on disk).
"""

from __future__ import annotations

import io

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class ParseResult(BaseModel):
    """Result of document parsing."""

    text: str
    page_count: int | None = None


class DocumentProcessor:
    """Parse documents (DOCX, PDF, TXT) to plain text."""

    def parse(self, content: bytes, format: str) -> ParseResult:
        """Parse document bytes into plain text.

        Args:
            content: Raw file bytes.
            format: File format ("docx", "pdf", "txt").

        Returns:
            ParseResult with extracted text and optional page count.

        Raises:
            ValueError: If format is unsupported.
        """
        if format == "txt":
            return self._parse_txt(content)
        if format == "docx":
            return self._parse_docx(content)
        if format == "pdf":
            return self._parse_pdf(content)
        raise ValueError(f"Unsupported format: {format}")

    def _parse_txt(self, content: bytes) -> ParseResult:
        """Parse plain text file."""
        text = content.decode("utf-8", errors="replace")
        return ParseResult(text=text)

    def _parse_docx(self, content: bytes) -> ParseResult:
        """Parse DOCX file using python-docx."""
        from docx import Document

        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        logger.info("doc_processor.docx", paragraphs=len(paragraphs))
        return ParseResult(text=text)

    def _parse_pdf(self, content: bytes) -> ParseResult:
        """Parse PDF file using PyMuPDF."""
        import pymupdf

        doc = pymupdf.open(stream=content, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        text = "\n".join(pages)
        page_count = len(pages)
        doc.close()
        logger.info("doc_processor.pdf", pages=page_count)
        return ParseResult(text=text, page_count=page_count)
