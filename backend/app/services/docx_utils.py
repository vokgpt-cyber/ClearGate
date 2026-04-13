"""Shared DOCX manipulation utilities.

Extracted from ``docx_export.py`` so that both export (anonymization)
and import (deanonymization) pipelines reuse the same paragraph
traversal and run-level replacement logic.
"""

from __future__ import annotations

import re
from typing import Iterable

from docx.document import Document as _DocxDocument
from docx.table import _Cell
from docx.text.paragraph import Paragraph


# Pre-compiled regex for detecting purely numeric strings (with optional
# thousands separators).  Used by _safe_replace to avoid "500" matching
# inside "500 000".
_NUMERIC_RE = re.compile(r"^[\d\s]+$")


def iter_paragraphs(document: _DocxDocument) -> Iterable[Paragraph]:
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


def _safe_replace(text: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` in ``text``, boundary-aware for numbers.

    For purely numeric ``old`` values (like "500"), avoids replacing
    inside larger numbers ("500 000") by requiring that the match is NOT
    preceded by a digit and NOT followed by optional whitespace + digit.

    BUG-2 fix: prevents "500" → [РАССТОЯНИЕ_1] from also eating "500"
    inside "500 000 рублей".
    """
    if _NUMERIC_RE.match(old.strip()):
        # Boundary-aware replacement for numeric strings
        pattern = re.compile(
            r"(?<!\d)" + re.escape(old) + r"(?!\s*\d)",
        )
        return pattern.sub(new, text)
    return text.replace(old, new)


def replace_in_paragraph(paragraph: Paragraph, old: str, new: str) -> int:
    """Replace all occurrences of ``old`` with ``new`` inside a paragraph.

    Tries single-run replacement first to preserve run-level formatting
    (bold, italic, font size). Falls back to cross-run concatenation
    when the entity spans multiple runs.

    Uses boundary-aware replacement for numeric strings to prevent
    substring collisions (e.g. "500" matching inside "500 000").

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
                replaced = _safe_replace(run.text, old, new)
                if replaced != run.text:
                    run.text = replaced
                    total += replaced.count(new)  # conservative upper bound
                    single_run_hit = True
                    break
        if single_run_hit:
            continue

        # Fall back to cross-run replacement: concatenate, replace, then
        # collapse everything into the first run. This loses per-character
        # formatting in this paragraph for subsequent runs but is correct.
        full = "".join(r.text for r in paragraph.runs)
        if old not in full:
            break
        new_full = _safe_replace(full, old, new)
        if new_full != full and paragraph.runs:
            paragraph.runs[0].text = new_full
            for r in paragraph.runs[1:]:
                r.text = ""
            total += 1
        break

    return total
