"""Anonymized DOCX export.

Two responsibilities, in order:

1. **Body substitution** — load the original DOCX via python-docx,
   walk every paragraph (incl. paragraphs nested inside tables), and
   replace each non-rejected entity's text with its registry-assigned
   placeholder.

2. **Metadata scrubbing** — wipe everything Word and the operating
   system silently attach to a .docx that could identify the author,
   their organization, their computer, or their editing timeline.
   Specifically:

     * ``docProps/core.xml`` — author, lastModifiedBy, title, subject,
       keywords, comments/description, category, contentStatus,
       version, identifier, revision, created/modified/lastPrinted.
     * ``docProps/app.xml`` — Company, Manager, HyperlinkBase,
       TitlesOfParts (Word mirrors the title here too!), Application.
     * ``docProps/thumbnail.jpeg`` — the visual preview of page 1 that
       Windows Explorer shows. Removed entirely because it still
       renders the un-anonymized original text. The corresponding
       Relationship in ``_rels/.rels`` is also stripped to keep the
       package valid after the part is gone.
     * All ``w:author`` / ``w:initials`` / ``w:date`` attributes
       anywhere in ``word/*.xml`` — tracked-changes and comment
       authorship metadata.
     * ZipInfo timestamps on every file inside the .docx (the ZIP
       container itself records per-entry mtimes) — normalized to the
       ZIP epoch (1980-01-01 00:00:00).

Design notes:

* The body substitution is intentionally naive — a per-run
  ``str.replace`` — so that single-run entities (which is 95%+ of
  names/addresses/INNs in typical legal DOCX files) keep their
  original character formatting (bold, italic, font size) in the
  exported file. For cross-run matches we fall back to collapsing the
  paragraph's runs into the first run, which loses per-character
  formatting in that one paragraph but still gets the substitution
  right. Conscious tradeoff for the demo-grade exporter — we do NOT
  rebuild the DOCX from scratch because that would throw away all
  document-level formatting (headers, numbering, tables, etc.).

* Rejected entities are skipped entirely — they stay as original text
  in the exported file, matching what the user sees in the right pane.

* Entities are processed longest-first to avoid prefix collisions
  (e.g. replacing "Москва" before "город Москва").

* We do NOT log the original text, the entity list, the placeholder
  mapping, or any scrubbed metadata values — privacy by design. Only
  aggregate counts make it to ``structlog``.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from docx import Document
from docx.document import Document as _DocxDocument
from docx.text.paragraph import Paragraph

from app.services.docx_utils import iter_paragraphs, replace_in_paragraph

logger = structlog.get_logger(__name__)


# Constant used anywhere the author/creator/initial has to be non-empty
# (Word tolerates empty strings in most places but some viewers choke).
_SCRUBBED_AUTHOR = "VELUM"
_SCRUBBED_INITIALS = "V"

# Files inside the .docx that have their ZipInfo timestamp normalized.
# Using the ZIP epoch (1980-01-01) is canonical — earlier dates are
# invalid in the ZIP file format.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# A fixed epoch for docProps/core.xml date fields. We use Unix epoch
# rather than ZIP epoch because it's the conventional "no timestamp"
# marker in the Office Open XML world.
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class EntitySubstitution:
    """A single (original text → placeholder) pair to apply."""

    text: str
    placeholder: str


# ═════════════════════════════════════════════════════════════════════
# Body substitution (uses shared iter_paragraphs / replace_in_paragraph
# from docx_utils — extracted to share with docx_deanonymize)
# ═════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════
# Metadata scrubbing — Stage 1: core properties via python-docx API
# ═════════════════════════════════════════════════════════════════════


def _scrub_core_properties(document: _DocxDocument) -> int:
    """Wipe identifying fields in ``docProps/core.xml``.

    Returns the number of properties that were actually touched.
    """
    cp = document.core_properties
    touched = 0

    def _set(attr: str, value) -> None:  # type: ignore[no-untyped-def]
        nonlocal touched
        try:
            current = getattr(cp, attr)
        except Exception:
            return
        if current == value:
            return
        try:
            setattr(cp, attr, value)
            touched += 1
        except Exception:
            # Some fields are read-only on certain python-docx versions.
            # Skipping is safer than raising during an export.
            pass

    # Identity / authorship — the two fields the user explicitly called out.
    _set("author", _SCRUBBED_AUTHOR)
    _set("last_modified_by", _SCRUBBED_AUTHOR)

    # Topic / description — often carries PII in Word templates
    # (e.g. title = "Договор Иванов И.И.").
    _set("title", "")
    _set("subject", "")
    _set("keywords", "")
    _set("comments", "")
    _set("category", "")
    _set("content_status", "")

    # Version / tracking identifiers.
    _set("version", "")
    _set("identifier", "")
    _set("revision", 1)

    # Timestamps — normalize to Unix epoch so there is no timing leak.
    _set("created", _UNIX_EPOCH)
    _set("modified", _UNIX_EPOCH)
    _set("last_printed", None)

    return touched


# ═════════════════════════════════════════════════════════════════════
# Metadata scrubbing — Stage 2: zip-level post-processing
# ═════════════════════════════════════════════════════════════════════


# Regexes used to rewrite identifying attributes inside XML bytes.
# We operate on bytes to avoid re-encoding issues.
_AUTHOR_ATTR_RE = re.compile(rb'w:author="[^"]*"')
_INITIALS_ATTR_RE = re.compile(rb'w:initials="[^"]*"')
_DATE_ATTR_RE = re.compile(rb'w:date="[^"]*"')
_LAST_MODIFIED_BY_RE = re.compile(rb"<cp:lastModifiedBy>[^<]*</cp:lastModifiedBy>")

# Replacement constants (as bytes).
_AUTHOR_REPLACEMENT = b'w:author="' + _SCRUBBED_AUTHOR.encode("ascii") + b'"'
_INITIALS_REPLACEMENT = b'w:initials="' + _SCRUBBED_INITIALS.encode("ascii") + b'"'
_DATE_REPLACEMENT = b'w:date="1970-01-01T00:00:00Z"'

# docProps/app.xml tags whose text content we empty.
_APP_SIMPLE_SCRUB_TAGS = ("Company", "Manager", "HyperlinkBase", "Application")

# Relationship element pointing to docProps/thumbnail.jpeg inside _rels/.rels.
# When we drop the thumbnail blob from the zip, the relationship becomes
# dangling and python-docx (and Word's strict open mode) refuses to load
# the file. Strip the relationship element wholesale. We match on the
# relationship Type substring "thumbnail" so the regex still matches if
# Word reorders the attributes inside the element.
_THUMBNAIL_REL_RE = re.compile(
    rb'<Relationship[^>]*Type="[^"]*thumbnail"[^>]*/>',
)


def _strip_thumbnail_rel(xml_bytes: bytes) -> tuple[bytes, bool]:
    """Remove the thumbnail Relationship from a `_rels/.rels` file.

    Returns the new bytes plus a flag indicating whether anything changed.
    """
    new_bytes, n = _THUMBNAIL_REL_RE.subn(b"", xml_bytes)
    return new_bytes, n > 0


def _rewrite_app_xml(xml_bytes: bytes) -> bytes:
    """Empty identifying tags in docProps/app.xml."""
    text = xml_bytes.decode("utf-8")

    for tag in _APP_SIMPLE_SCRUB_TAGS:
        text = re.sub(
            rf"<{tag}>[^<]*</{tag}>",
            f"<{tag}></{tag}>",
            text,
        )
        text = re.sub(
            rf"<{tag}\s*/>",
            f"<{tag}></{tag}>",
            text,
        )

    # TitlesOfParts: blank the vector contents (Word reconstructs it on
    # first save, but until then it leaks the original title).
    text = re.sub(
        r"<TitlesOfParts>.*?</TitlesOfParts>",
        '<TitlesOfParts><vt:vector size="0" baseType="lpstr"></vt:vector></TitlesOfParts>',
        text,
        flags=re.DOTALL,
    )

    return text.encode("utf-8")


def _scrub_word_xml(xml_bytes: bytes) -> bytes:
    """Scrub tracked-change / comment authorship inside word/*.xml files."""
    data = _AUTHOR_ATTR_RE.sub(_AUTHOR_REPLACEMENT, xml_bytes)
    data = _INITIALS_ATTR_RE.sub(_INITIALS_REPLACEMENT, data)
    data = _DATE_ATTR_RE.sub(_DATE_REPLACEMENT, data)
    return data


def _scrub_core_xml_belt_and_braces(xml_bytes: bytes) -> bytes:
    """Extra safety net for cp:lastModifiedBy in docProps/core.xml."""
    return _LAST_MODIFIED_BY_RE.sub(
        f"<cp:lastModifiedBy>{_SCRUBBED_AUTHOR}</cp:lastModifiedBy>".encode("utf-8"),
        xml_bytes,
    )


def _post_process_metadata(docx_bytes: bytes) -> tuple[bytes, dict[str, int]]:
    """Rewrite every metadata-bearing part of the .docx zip.

    Returns the new bytes plus a dict of aggregate counts suitable for
    logging (contains only numeric counters, never any scrubbed values).
    """
    counters = {
        "app_xml_rewritten": 0,
        "core_xml_rewritten": 0,
        "word_xml_scrubbed": 0,
        "thumbnail_removed": 0,
        "thumbnail_rel_stripped": 0,
        "custom_xml_touched": 0,
        "entries_normalized": 0,
    }

    src = io.BytesIO(docx_bytes)
    dst = io.BytesIO()

    with zipfile.ZipFile(src, "r") as zin:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                name = item.filename

                # Drop the visual thumbnail — it is a JPEG preview of
                # page 1 rendered by Word at the time of last save, and
                # it still shows the un-anonymized original text.
                if name == "docProps/thumbnail.jpeg":
                    counters["thumbnail_removed"] = 1
                    continue

                data = zin.read(name)

                if name == "_rels/.rels":
                    data, stripped = _strip_thumbnail_rel(data)
                    if stripped:
                        counters["thumbnail_rel_stripped"] = 1
                elif name == "docProps/app.xml":
                    data = _rewrite_app_xml(data)
                    counters["app_xml_rewritten"] = 1
                elif name == "docProps/core.xml":
                    data = _scrub_core_xml_belt_and_braces(data)
                    counters["core_xml_rewritten"] = 1
                elif name.startswith("word/") and name.endswith(".xml"):
                    new_data = _scrub_word_xml(data)
                    if new_data != data:
                        counters["word_xml_scrubbed"] += 1
                        data = new_data
                elif name == "docProps/custom.xml" or name.startswith("customXml/"):
                    # We deliberately do NOT rewrite customXml/* because
                    # removing or altering it can break document
                    # integrity (Word relies on specific item IDs in
                    # item1.xml for template bindings).
                    counters["custom_xml_touched"] += 1

                # Normalize the per-entry ZipInfo timestamp to the ZIP
                # epoch so that "when was this file saved" can't be
                # read out of the container itself.
                new_info = zipfile.ZipInfo(filename=name, date_time=_ZIP_EPOCH)
                new_info.compress_type = item.compress_type
                new_info.external_attr = item.external_attr
                counters["entries_normalized"] += 1

                zout.writestr(new_info, data)

    return dst.getvalue(), counters


# ═════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════


def export_anonymized_docx(
    docx_bytes: bytes,
    substitutions: list[EntitySubstitution],
) -> bytes:
    """Return a new DOCX with all substitutions applied and metadata scrubbed.

    Args:
        docx_bytes: Raw bytes of the original DOCX file (from
            ``session.docx_bytes``).
        substitutions: Entities to replace. Rejected entities should be
            filtered out by the caller BEFORE this function is called.

    Returns:
        Bytes of the modified DOCX file, ready to stream to the client.
    """
    document = Document(io.BytesIO(docx_bytes))

    # Stage 1: body substitution.
    ordered = sorted(
        (s for s in substitutions if s.text and s.placeholder),
        key=lambda s: len(s.text),
        reverse=True,
    )

    applied = 0
    skipped = 0
    for sub in ordered:
        paragraph_hits = 0
        for paragraph in iter_paragraphs(document):
            paragraph_hits += replace_in_paragraph(paragraph, sub.text, sub.placeholder)
        if paragraph_hits > 0:
            applied += 1
        else:
            skipped += 1

    # Stage 2a: scrub what the python-docx API can touch.
    props_touched = _scrub_core_properties(document)

    # Save to an intermediate buffer.
    buffer = io.BytesIO()
    document.save(buffer)

    # Stage 2b: zip-level post-processing — app.xml, thumbnail, word/*.xml
    # tracked-change authors, ZipInfo timestamps, belt-and-braces core.xml.
    scrubbed_bytes, scrub_counters = _post_process_metadata(buffer.getvalue())

    logger.info(
        "docx_export.completed",
        substitutions_in=len(substitutions),
        applied=applied,
        skipped=skipped,
        core_properties_touched=props_touched,
        output_bytes=len(scrubbed_bytes),
        **scrub_counters,
    )
    return scrubbed_bytes
