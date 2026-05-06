"""DOCX deanonymization — reverse placeholder substitution with fuzzy matching.

Mirrors ``docx_export.py`` but in the opposite direction: replaces
placeholders like ``[ЛИЦО_1]`` with their real values from the
EntityRegistry mapping table.

Key capability beyond simple string replacement: **PlaceholderMatcher**
handles the many ways an LLM can distort placeholder formatting:

  * Missing or extra brackets: ``ЛИЦО_1``, ``[ ЛИЦО_1 ]``
  * Spaces instead of underscores: ``[ЛИЦО 1]``
  * Dashes instead of underscores: ``[ЛИЦО-1]``
  * Lowercase: ``[лицо_1]``
  * English label when registry is Russian: ``[Person_1]``
  * Leading zeros: ``[ЛИЦО_01]``
  * Levenshtein-close typos: ``[ЛИЦО_!]`` (distance 1 from ``[ЛИЦО_1]``)
  * **Custom types**: ``[РАССТОЯНИЕ_1]``, ``[ЧАСЫ_1]`` — any label the
    user defined via the UI.

Design: we scan every paragraph for placeholder-like patterns via a
generous regex, normalize each match, then look it up in the registry.
Anything that matches the pattern but can't be resolved → ``unresolved``.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import structlog
from docx import Document
from Levenshtein import distance as levenshtein_distance

from app.models.api import UnresolvedPlaceholder
from app.services.docx_utils import (
    iter_paragraphs,
    replace_first_in_paragraph,
    replace_in_paragraph,
    replace_in_paragraph_highlighted,
)
from app.services.entity_registry import EntityRegistry, _EN_LABELS, _RU_LABELS

logger = structlog.get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
# Label cross-language mapping
# ═════════════════════════════════════════════════════════════════════

# Build bidirectional EN↔RU label maps from the registry's own label dicts.
# e.g. "PERSON" ↔ "ЛИЦО", "ORG" ↔ "ОРГАНИЗАЦИЯ"
_EN_TO_RU: dict[str, str] = {}
_RU_TO_EN: dict[str, str] = {}
for _etype, _ru_label in _RU_LABELS.items():
    _en_label = _EN_LABELS.get(_etype, "")
    if _en_label:
        _EN_TO_RU[_en_label.upper()] = _ru_label.upper()
        _RU_TO_EN[_ru_label.upper()] = _en_label.upper()

# All known labels (both languages) for the static scanner regex.
_ALL_LABELS: set[str] = set()
for _lbl in _RU_LABELS.values():
    _ALL_LABELS.add(_lbl.upper())
for _lbl in _EN_LABELS.values():
    _ALL_LABELS.add(_lbl.upper())


def _build_placeholder_re(extra_labels: set[str] | None = None) -> re.Pattern[str]:
    """Build a placeholder scanner regex from known + extra labels.

    If ``extra_labels`` is given, they're merged with the static
    ``_ALL_LABELS`` set so custom entity types are recognized too.

    When no labels are available at all, falls back to a generic
    pattern that requires brackets: ``[WORD_N]``.
    """
    labels = set(_ALL_LABELS)
    if extra_labels:
        labels |= extra_labels

    if not labels:
        # Fallback: any bracketed WORD_N
        return re.compile(
            r"\[\s*([A-ZА-ЯЁa-zа-яё][A-ZА-ЯЁa-zа-яё]*)\s*[-_\s]\s*0*(\d+)\s*\]",
            re.IGNORECASE,
        )

    # Sort by length descending so longer labels match first in the regex
    pattern = "|".join(
        re.escape(lbl) for lbl in sorted(labels, key=len, reverse=True)
    )

    # Two alternatives:
    # 1) Known/extra labels — brackets optional (handles LLM distortions)
    # 2) Any CYR/LAT word as label — brackets REQUIRED (catches unknown custom types)
    return re.compile(
        r"\[?\s*(?:" + pattern + r")\s*[-_\s]\s*0*(\d+)\s*\]?"
        + r"|\[\s*([A-ZА-ЯЁa-zа-яё][A-ZА-ЯЁa-zа-яё]*)\s*[-_\s]\s*0*(\d+)\s*\]",
        re.IGNORECASE,
    )


# Module-level regex for static usage (scan_placeholders).
_PLACEHOLDER_RE = _build_placeholder_re()


# ═════════════════════════════════════════════════════════════════════
# PlaceholderMatcher
# ═════════════════════════════════════════════════════════════════════


@dataclass
class MatchResult:
    """Result of matching a single placeholder occurrence."""

    raw_text: str  # exact text matched by regex in the document
    normalized: str  # canonical form e.g. "[ЛИЦО_1]"
    real_value: str | None = None  # resolved value, or None if unresolved
    paragraph_index: int = 0


@dataclass
class DeanonymizeResult:
    """Aggregate result from deanonymizing a DOCX."""

    docx_bytes: bytes = b""
    replacements: list[MatchResult] = field(default_factory=list)
    unresolved: list[MatchResult] = field(default_factory=list)


class PlaceholderMatcher:
    """Resolves placeholder-like strings against an EntityRegistry.

    The matcher tries multiple normalization strategies to handle
    LLM-induced distortions of placeholder format.

    On init, builds a **dynamic** regex from all labels present in the
    registry — including custom user-defined types (РАССТОЯНИЕ, ЧАСЫ,
    КЛИЕНТ, etc.) that aren't in the static ``_ALL_LABELS`` set.
    """

    def __init__(self, registry: EntityRegistry) -> None:
        self._registry = registry
        self._reverse = registry._reverse  # placeholder → MappingEntry
        self._locale = registry.locale

        # BUG-1 fix: extract label set from actual registry placeholders
        # so custom types like [РАССТОЯНИЕ_1] are included in the scanner.
        extra = self._extract_registry_labels()
        self._re = _build_placeholder_re(extra)

    def _extract_registry_labels(self) -> set[str]:
        """Pull label stems from every placeholder in the registry."""
        labels: set[str] = set()
        for placeholder in self._reverse:
            inner = placeholder.strip("[]")
            parts = inner.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                labels.add(parts[0].upper())
        return labels

    @staticmethod
    def _get_real_value(entry, occurrence_index: int = 0) -> str:
        """Return the best real-world form of an entity for a given occurrence.

        Resolution order (BUG-P2-2, Layer 2):

        1. ``surface_forms[occurrence_index]`` — the exact inflected form
           from the *Nth* occurrence in the original document (built at
           export time by :meth:`EntityRegistry.record_surface_forms`).
        2. ``original_forms[0]`` — first unique form seen during detection
           (BUG-7 fix; preserves case and inflection for single-form entities).
        3. ``canonical_value`` — normalized lemma (last resort).
        """
        if entry.surface_forms and occurrence_index < len(entry.surface_forms):
            return entry.surface_forms[occurrence_index]
        if entry.original_forms:
            return entry.original_forms[0]
        return entry.canonical_value

    def match(
        self,
        raw_text: str,
        occurrence_index: int = 0,
    ) -> tuple[str, str | None]:
        """Attempt to resolve a raw placeholder-like string.

        Args:
            raw_text: The text matched by the scanner regex.
            occurrence_index: How many times this *normalized* placeholder
                has already been seen in the current deanonymization pass.
                Used to pick the correct ``surface_forms`` entry.

        Returns:
            (normalized_placeholder, real_value_or_None)
        """
        normalized = self._normalize(raw_text)

        # 1. Exact match
        if normalized in self._reverse:
            return normalized, self._get_real_value(self._reverse[normalized], occurrence_index)

        # 2. Cross-language: if registry is RU but LLM wrote EN label (or vice versa)
        cross = self._cross_language(normalized)
        if cross and cross in self._reverse:
            return cross, self._get_real_value(self._reverse[cross], occurrence_index)

        # 3. Fuzzy match against all known placeholders (Levenshtein ≤ 2)
        fuzzy = self._fuzzy_match(normalized)
        if fuzzy:
            return fuzzy, self._get_real_value(self._reverse[fuzzy], occurrence_index)

        # 4. Fuzzy on cross-language variant
        if cross:
            fuzzy_cross = self._fuzzy_match(cross)
            if fuzzy_cross:
                return fuzzy_cross, self._get_real_value(self._reverse[fuzzy_cross], occurrence_index)

        return normalized, None

    def _normalize(self, raw: str) -> str:
        """Normalize a raw placeholder string to canonical form ``[LABEL_N]``."""
        m = self._re.search(raw)
        if not m:
            # Can't parse — return stripped/uppercased as-is
            stripped = raw.strip().strip("[]").strip()
            generic = re.match(r"^(.+?)\s*[-_\s]\s*0*(\d+)$", stripped)
            if generic:
                label = re.sub(r"\s+", "_", generic.group(1).strip()).upper()
                number = generic.group(2).lstrip("0") or "1"
                return f"[{label}_{number}]"
            return f"[{stripped.upper()}]"

        # The regex has two alternatives with different group layouts:
        # Alt 1 (known labels): group(1) = number
        # Alt 2 (generic bracketed): group(2) = label, group(3) = number
        if m.group(2) is not None:
            # Generic bracketed match
            label = m.group(2).upper()
            number = m.group(3).lstrip("0") or "1"
        else:
            # Known/extra label match — extract label from the matched text
            number = m.group(1).lstrip("0") or "1"
            # The label is everything in the match before the separator+number
            full = m.group(0)
            label_part = full.strip().strip("[]").strip()
            # Remove trailing separator + number
            label_part = re.sub(r'\s*[-_\s]\s*0*\d+\s*$', '', label_part)
            label = label_part.upper()

        return f"[{label}_{number}]"

    def _cross_language(self, normalized: str) -> str | None:
        """Translate label between EN↔RU."""
        # Extract label from "[LABEL_N]"
        inner = normalized.strip("[]")
        parts = inner.rsplit("_", 1)
        if len(parts) != 2:
            return None
        label, number = parts[0], parts[1]

        if self._locale == "ru":
            # Registry is RU; LLM might have written EN label
            ru_label = _EN_TO_RU.get(label)
            if ru_label:
                return f"[{ru_label}_{number}]"
        else:
            # Registry is EN; LLM might have written RU label
            en_label = _RU_TO_EN.get(label)
            if en_label:
                return f"[{en_label}_{number}]"
        return None

    def _fuzzy_match(self, normalized: str, max_dist: int = 2) -> str | None:
        """Find closest placeholder in registry by Levenshtein distance.

        Number-aware: only fuzzy-matches when the *label* part is close
        AND the numeric suffix is identical. Changing ``[ЛИЦО_1]`` to
        ``[ЛИЦО_5]`` is a different entity, not a typo — Levenshtein
        distance 1 between them must NOT produce a match.

        Length-proportional threshold (BUG-P2-1 fix):
        - 4-letter labels allow ≤ 1 edit (so ``АФТА`` stays distinct
          from ``ДАТА`` — they differ by 2 substitutions)
        - 8-letter labels allow ≤ 2 edits
        - longer labels cap at ``max_dist``
        Before this fix a flat ``max_dist=2`` silently collapsed any
        pair of 4-char Cyrillic labels that shared two characters.
        """
        # Parse the label and number from the normalized form
        norm_label, norm_num = self._split_placeholder(normalized)
        if norm_label is None:
            return None

        best: str | None = None
        best_dist_weighted: float = float("inf")
        for known in self._reverse:
            known_label, known_num = self._split_placeholder(known)
            if known_label is None:
                continue
            # Numbers must match exactly — different numbers = different entities
            if norm_num != known_num:
                continue
            # Budget scales with the SHORTER label so distance isn't
            # spent on padding from a much longer registry entry.
            budget = min(max_dist, min(len(norm_label), len(known_label)) // 4)
            if budget <= 0:
                # Below 4 chars we require exact label match, otherwise
                # any single edit is a 25%+ deformation and far too
                # likely to be a distinct concept (АФТА vs ДАТА).
                if norm_label == known_label:
                    return known
                continue
            d = levenshtein_distance(norm_label, known_label)
            if d <= budget and d < best_dist_weighted:
                best_dist_weighted = d
                best = known
        return best

    @staticmethod
    def _split_placeholder(placeholder: str) -> tuple[str | None, str | None]:
        """Split ``[LABEL_N]`` into (label, number) or (None, None)."""
        inner = placeholder.strip("[]")
        parts = inner.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], parts[1]
        return None, None


# ═════════════════════════════════════════════════════════════════════
# Scanning and replacement
# ═════════════════════════════════════════════════════════════════════


def scan_placeholders(text: str) -> list[re.Match[str]]:
    """Find all placeholder-like patterns in plain text."""
    return list(_PLACEHOLDER_RE.finditer(text))


def deanonymize_docx(
    docx_bytes: bytes,
    registry: EntityRegistry,
    manual_resolutions: dict[str, str] | None = None,
    highlight: bool = False,
) -> DeanonymizeResult:
    """Deanonymize a DOCX file by replacing placeholders with real values.

    Args:
        docx_bytes: Raw bytes of the DOCX containing placeholders.
        registry: The session's EntityRegistry with the mapping table.
        manual_resolutions: Optional dict of ``normalized_placeholder → value``
            for unresolved placeholders the user filled in manually.

    Returns:
        ``DeanonymizeResult`` with the output DOCX bytes, list of successful
        replacements, and list of unresolved placeholders.
    """
    matcher = PlaceholderMatcher(registry)
    manual: dict[str, str] = {}
    for raw_key, value in (manual_resolutions or {}).items():
        if not raw_key or value is None:
            continue
        manual[matcher._normalize(raw_key)] = value
    document = Document(io.BytesIO(docx_bytes))

    # Phase 1: scan all paragraphs in document order, collecting an
    # *ordered* list of (raw_text, real_value) pairs.  BUG-P2-2 Layer 2:
    # we track a per-placeholder occurrence counter so each [МЕСТО_1]
    # gets the surface form from the matching original occurrence
    # (e.g. "Москве" for the 1st, "Москва" for the 2nd).
    ordered_subs: list[tuple[str, str]] = []  # (raw_text, real_value), document order
    replacements: list[MatchResult] = []
    unresolved: list[MatchResult] = []
    seen_raw: set[str] = set()  # deduplicate logging, not substitution
    occurrence_counters: dict[str, int] = {}  # normalized → next index

    for para_idx, paragraph in enumerate(iter_paragraphs(document)):
        full_text = paragraph.text
        if not full_text:
            continue

        # Use the matcher's dynamic regex (includes custom types).
        for m in matcher._re.finditer(full_text):
            raw = m.group(0)
            # Peek at the normalized form to get the occurrence index
            normalized_peek = matcher._normalize(raw)
            occ_idx = occurrence_counters.get(normalized_peek, 0)
            occurrence_counters[normalized_peek] = occ_idx + 1

            normalized, real_value = matcher.match(raw, occurrence_index=occ_idx)

            # Check manual resolutions if registry didn't have it
            if real_value is None and normalized in manual:
                real_value = manual[normalized]

            result = MatchResult(
                raw_text=raw,
                normalized=normalized,
                real_value=real_value,
                paragraph_index=para_idx,
            )

            if real_value is not None:
                ordered_subs.append((raw, real_value))
                if raw not in seen_raw:
                    replacements.append(result)
                    seen_raw.add(raw)
            else:
                unresolved.append(result)

    # Phase 2: apply substitutions to the DOCX paragraphs.
    #
    # BUG-P2-2 Layer 2 — occurrence-aware replacement.
    # Build a value queue for each raw text.  If all queued values for a
    # raw text are identical we can use the fast bulk-replace path; when
    # they differ we pop values one-at-a-time via replace_first so each
    # placeholder instance gets its own surface form.
    from collections import deque

    value_queues: dict[str, deque[str]] = {}
    for raw, value in ordered_subs:
        value_queues.setdefault(raw, deque()).append(value)

    # Partition: uniform (all same value) vs mixed (different values).
    uniform: dict[str, str] = {}
    mixed: set[str] = set()
    for raw, q in value_queues.items():
        unique_vals = set(q)
        if len(unique_vals) == 1:
            uniform[raw] = q[0]
        else:
            mixed.add(raw)

    total_applied = 0
    replace_fn = (
        replace_in_paragraph_highlighted if highlight else replace_in_paragraph
    )

    # Fast path: uniform raw texts → bulk replace (preserves old behavior).
    uniform_ordered = sorted(uniform.items(), key=lambda kv: len(kv[0]), reverse=True)
    for raw, value in uniform_ordered:
        for paragraph in iter_paragraphs(document):
            total_applied += replace_fn(paragraph, raw, value)

    # Slow path: mixed raw texts → per-occurrence replacement.
    # Process paragraphs in document order, consuming from the queue.
    if mixed:
        for paragraph in iter_paragraphs(document):
            # Each replacement changes the paragraph text, so re-scan
            # until no more matches from the mixed set are found.
            changed = True
            while changed:
                changed = False
                full_text = paragraph.text
                if not full_text:
                    break
                for m in matcher._re.finditer(full_text):
                    raw = m.group(0)
                    if raw not in mixed:
                        continue
                    q = value_queues.get(raw)
                    if not q:
                        continue
                    value = q.popleft()
                    total_applied += replace_first_in_paragraph(paragraph, raw, value)
                    changed = True
                    break  # re-scan paragraph after text mutation

    # Save modified DOCX.
    buffer = io.BytesIO()
    document.save(buffer)

    logger.info(
        "docx_deanonymize.completed",
        total_replacements=total_applied,
        unique_placeholders=len(value_queues),
        unresolved_count=len(unresolved),
    )

    return DeanonymizeResult(
        docx_bytes=buffer.getvalue(),
        replacements=replacements,
        unresolved=unresolved,
    )
