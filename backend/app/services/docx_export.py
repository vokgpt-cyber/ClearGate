"""Anonymized DOCX export.

Loads the original DOCX that was uploaded for a session, walks every
paragraph (including paragraphs nested inside tables), and replaces each
non-rejected entity's original text with its registry-assigned
placeholder (e.g. ``[ЛИЦО_1]``).

Design notes:

* The replacement is intentionally naive — a per-run ``str.replace`` —
  so that single-run entities (which is 95%+ of names/addresses/INNs in
  typical legal DOCX files) keep their original character formatting
  (bold, italic, font size) in the exported file. For cross-run matches
  we fall back to collapsing the paragraph's runs into the first run,
  which loses per-character formatting in that one paragraph but still
  gets the substitution right. This is a conscious tradeoff for the
  demo-grade exporter — we do NOT rebuild the DOCX from scratch because
  that would throw away all document-level formatting (headers,
  numbering, tables, etc.).

* Rejected entities are skipped entirely — they stay as original text
  in the exported file, matching what the user sees in the right pane.

* Entities are processed longest-first to avoid prefix collisions
  (e.g. replacing "Москва" before "город Москва").

* We do NOT log the original text, the entity list, or the placeholder
  mapping — privacy by design. Only aggregate counts make it to
  ``structlog``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

import structlog
from docx import Document
from docx.document import Document as _DocxDocument
from docx.table import _Cell
from docx.text.paragraph import Paragraph

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EntitySubstitution:
    """A single (original text → placeholder) pair to apply."""

    text: str
    placeholder: str


def _iter_paragraphs(document: _DocxDocument) -> Iterable[Paragraph]:
    """Yield every paragraph in document order, descending into tables."""
    for paragraph in document.paragraphs:
        yield paragraph
    for table in document.tables:
        yield from _iter_table_paragraphs(table)


def _iter_table_paragraphs(table) -> Iterable[Paragraph]:  # type: ignore[no-untyped-def]
    for row in table.rows:
        for cell in row.cells:
            yield from _iter_cell_paragraphs(cell)


def _iter_cell_paragraphs(cell: _Cell) -> Iterable[Paragraph]:
    for paragraph in cell.paragraphs:
        yield paragraph
    for nested in cell.tables:
        yield from _iter_table_paragraphs(nested)


def _replace_in_paragraph(paragraph: Paragraph, old: str, new: str) -> int:
    """Replace all occurrences of ``old`` with ``new`` inside a paragraph.

    Returns the number of substitutions made.
    """
    if not old:
        return 0

    total = 0
    # Try to find each occurrence inside a single run first so we preserve
    # run-level formatting. Loop because one run may contain the same
    # entity more than once (e.g. the word "Москва" appearing twice in the
    # same sentence).
    while True:
        single_run_hit = False
        for run in paragraph.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)
                total += run.text.count(new)  # conservative upper bound
                single_run_hit = True
                break
        if single_run_hit:
            # Re-scan from the start — the run list didn't shrink but we
            # may have more entities of the same text in other runs.
            continue

        # Fall back to cross-run replacement: concatenate, replace, then
        # collapse everything into the first run. This loses per-character
        # formatting in this paragraph for subsequent runs but is correct.
        full = "".join(r.text for r in paragraph.runs)
        if old not in full:
            break
        new_full = full.replace(old, new)
        if paragraph.runs:
            paragraph.runs[0].text = new_full
            for r in paragraph.runs[1:]:
                r.text = ""
            # Each paragraph is collapsed at most once per call; bail.
            total += 1
        break

    return total


def export_anonymized_docx(
    docx_bytes: bytes,
    substitutions: list[EntitySubstitution],
) -> bytes:
    """Return a new DOCX with all substitutions applied.

    Args:
        docx_bytes: Raw bytes of the original DOCX file (from
            ``session.docx_bytes``).
        substitutions: Entities to replace. Rejected entities should be
            filtered out by the caller BEFORE this function is called.

    Returns:
        Bytes of the modified DOCX file, ready to stream to the client.
    """
    document = Document(io.BytesIO(docx_bytes))

    # Process longest-first so "город Москва" wins over "Москва".
    ordered = sorted(
        (s for s in substitutions if s.text and s.placeholder),
        key=lambda s: len(s.text),
        reverse=True,
    )

    applied = 0
    skipped = 0
    for sub in ordered:
        paragraph_hits = 0
        for paragraph in _iter_paragraphs(document):
            paragraph_hits += _replace_in_paragraph(paragraph, sub.text, sub.placeholder)
        if paragraph_hits > 0:
            applied += 1
        else:
            skipped += 1

    buffer = io.BytesIO()
    document.save(buffer)
    logger.info(
        "docx_export.completed",
        substitutions_in=len(substitutions),
        applied=applied,
        skipped=skipped,
        output_bytes=buffer.tell(),
    )
    return buffer.getvalue()
