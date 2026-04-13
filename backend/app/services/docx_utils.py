"""Shared DOCX manipulation utilities.

Extracted from ``docx_export.py`` so that both export (anonymization)
and import (deanonymization) pipelines reuse the same paragraph
traversal and run-level replacement logic.
"""

from __future__ import annotations

from typing import Iterable

from docx.document import Document as _DocxDocument
from docx.table import _Cell
from docx.text.paragraph import Paragraph


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


def replace_in_paragraph(paragraph: Paragraph, old: str, new: str) -> int:
    """Replace all occurrences of ``old`` with ``new`` inside a paragraph.

    Tries single-run replacement first to preserve run-level formatting
    (bold, italic, font size). Falls back to cross-run concatenation
    when the entity spans multiple runs.

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
            total += 1
        break

    return total
