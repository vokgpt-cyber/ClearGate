"""Shared DOCX manipulation utilities.

Extracted from ``docx_export.py`` so that both export (anonymization)
and import (deanonymization) pipelines reuse the same paragraph
traversal and run-level replacement logic.
"""

from __future__ import annotations

import re
from typing import Iterable

from copy import deepcopy

from docx.document import Document as _DocxDocument
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
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


def copy_page_setup(source_bytes: bytes, target_bytes: bytes) -> bytes:
    """Make ``target_bytes`` visually match ``source_bytes`` in page geometry
    and default text styling.

    The LLM's response DOCX typically has its own section properties
    (page size / margins / columns / doc grid) and its own stylesheet
    defaults (font, size, paragraph spacing).  To make the deanonymized
    preview pane look the same as the original on the left, we:

    1. Replace the target's ``w:sectPr`` (body-level section properties)
       wholesale with a deep copy of the source's.  This brings over
       ``pgSz``, ``pgMar``, ``cols``, ``docGrid``, ``type``, etc.
    2. Replace ``word/styles.xml`` with the source's so default paragraph
       / run properties (font, size, line spacing) match.

    Fails soft on any error — returns ``target_bytes`` unchanged.  Does
    NOT touch numbering, themes, or the actual content.
    """
    import io as _io
    import zipfile as _zip

    from docx import Document as _Document

    # --- Step 1: sectPr transplant via python-docx -----------------------
    try:
        src = _Document(_io.BytesIO(source_bytes))
        tgt = _Document(_io.BytesIO(target_bytes))

        src_sectPr = src.element.body.find(qn("w:sectPr"))
        tgt_sectPr = tgt.element.body.find(qn("w:sectPr"))
        if src_sectPr is not None and tgt_sectPr is not None:
            parent = tgt_sectPr.getparent()
            idx = list(parent).index(tgt_sectPr)
            parent.remove(tgt_sectPr)
            parent.insert(idx, deepcopy(src_sectPr))

        buf = _io.BytesIO()
        tgt.save(buf)
        target_bytes = buf.getvalue()
    except Exception:  # pragma: no cover — fail soft
        return target_bytes

    # --- Step 2: styles.xml transplant via zipfile -----------------------
    # python-docx does not expose a clean API for replacing the whole
    # stylesheet, so we rebuild the .docx zip with the source's
    # word/styles.xml in place of the target's.
    try:
        with _zip.ZipFile(_io.BytesIO(source_bytes)) as src_zip:
            if "word/styles.xml" not in src_zip.namelist():
                return target_bytes
            src_styles = src_zip.read("word/styles.xml")

        out = _io.BytesIO()
        with _zip.ZipFile(_io.BytesIO(target_bytes)) as tgt_zip, _zip.ZipFile(
            out, "w", _zip.ZIP_DEFLATED
        ) as new_zip:
            for item in tgt_zip.infolist():
                if item.filename == "word/styles.xml":
                    new_zip.writestr(item, src_styles)
                else:
                    new_zip.writestr(item, tgt_zip.read(item.filename))
        return out.getvalue()
    except Exception:  # pragma: no cover — fail soft
        return target_bytes


def _make_run_like(template_r, text: str, highlight_color: str | None = None):
    """Clone a <w:r> element, replace its text, optionally add a highlight.

    Preserves rPr (bold/italic/font/size/color) from the template run so
    highlighted replacements keep the visual style of the surrounding text.
    """
    new_r = deepcopy(template_r)
    # Strip all existing <w:t> children; keep <w:rPr>
    for child in list(new_r):
        if child.tag != qn("w:rPr"):
            new_r.remove(child)

    if highlight_color:
        rPr = new_r.find(qn("w:rPr"))
        if rPr is None:
            rPr = OxmlElement("w:rPr")
            new_r.insert(0, rPr)
        # Remove any prior highlight
        for h in rPr.findall(qn("w:highlight")):
            rPr.remove(h)
        highlight = OxmlElement("w:highlight")
        highlight.set(qn("w:val"), highlight_color)
        rPr.append(highlight)

    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    new_r.append(t)
    return new_r


def replace_in_paragraph_highlighted(
    paragraph: Paragraph,
    old: str,
    new: str,
    highlight_color: str = "yellow",
) -> int:
    """Replace ``old`` with ``new`` and wrap the replacement in a highlighted run.

    The replacement text gets a ``w:highlight`` element (yellow by default)
    so the reader can visually distinguish restored values in the
    deanonymized document.  Surrounding run formatting (bold, font, etc.)
    is preserved by cloning the source run's ``w:rPr``.

    Cross-run matches fall back to a collapse-and-highlight strategy that
    may drop per-character formatting for the paragraph (same trade-off
    as :func:`replace_in_paragraph`).

    Returns the number of substitutions made.
    """
    if not old:
        return 0

    total = 0

    # Single-run path — walk runs by list index so we can insert siblings.
    while True:
        hit = False
        # Re-fetch runs each iteration since we may have added runs.
        runs = list(paragraph.runs)
        for run in runs:
            if not run.text or old not in run.text:
                continue
            # Use _safe_replace semantics to find a valid match position
            probe = _safe_replace(run.text, old, "\x00")
            if "\x00" not in probe:
                continue
            idx = probe.find("\x00")
            before = run.text[:idx]
            after = run.text[idx + len(old):]

            original_r = run._r
            parent = original_r.getparent()
            insert_at = list(parent).index(original_r) + 1

            # Turn the current run into the "before" slice
            run.text = before

            # Build highlighted run for the replacement value
            hl_r = _make_run_like(original_r, new, highlight_color=highlight_color)
            # Build plain run for the tail
            tail_r = _make_run_like(original_r, after, highlight_color=None)

            parent.insert(insert_at, hl_r)
            parent.insert(insert_at + 1, tail_r)

            total += 1
            hit = True
            break
        if hit:
            continue

        # Cross-run fallback: concatenate, splice once, rebuild paragraph body.
        full = "".join(r.text for r in paragraph.runs)
        if not paragraph.runs or old not in full:
            break
        probe = _safe_replace(full, old, "\x00")
        if "\x00" not in probe:
            break
        idx = probe.find("\x00")
        before = full[:idx]
        after = full[idx + len(old):]

        first_r = paragraph.runs[0]._r
        parent = first_r.getparent()
        insert_at = list(parent).index(first_r) + 1

        paragraph.runs[0].text = before
        for r in paragraph.runs[1:]:
            r.text = ""

        hl_r = _make_run_like(first_r, new, highlight_color=highlight_color)
        tail_r = _make_run_like(first_r, after, highlight_color=None)
        parent.insert(insert_at, hl_r)
        parent.insert(insert_at + 1, tail_r)
        total += 1
        break

    return total
