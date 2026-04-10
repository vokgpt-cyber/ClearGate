"""Entity normalization for consistent placeholder mapping.

Normalizes Russian entity text to a canonical form that is stable
across morphological variations (declensions, abbreviations, legal forms).
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# Legal forms to strip from organization names
_LEGAL_FORMS = [
    "общество с ограниченной ответственностью",
    "открытое акционерное общество",
    "закрытое акционерное общество",
    "публичное акционерное общество",
    "акционерное общество",
    "ооо",
    "оао",
    "зао",
    "пао",
    "ао",
    "ип",
]


class RussianEntityNormalizer:
    """Normalize Russian entities to canonical form for registry lookup.

    Uses pymorphy3 for morphological analysis and Natasha for name parsing.

    Examples:
        >>> normalizer = RussianEntityNormalizer()
        >>> normalizer.normalize("Иванова Ивана Ивановича", "PER")
        'иванов иван иванович'
        >>> normalizer.normalize('ООО «Ромашка»', "ORG")
        'ромашка'
    """

    def __init__(self) -> None:
        import pymorphy3

        self._morph = pymorphy3.MorphAnalyzer()

    def normalize(self, text: str, entity_type: str) -> str:
        """Normalize entity text based on its type.

        Args:
            text: Raw entity text.
            entity_type: Entity type (PER, ORG, ADDR, etc.).

        Returns:
            Normalized canonical form, lowercased.
        """
        text = text.strip()
        if not text:
            return text

        if entity_type == "PER":
            return self._normalize_person(text)
        if entity_type == "ORG":
            return self._normalize_org(text)
        # Default: lowercase and collapse whitespace
        return " ".join(text.lower().split())

    def _normalize_person(self, text: str) -> str:
        """Normalize person name via pymorphy3 lemmatization."""
        words = text.lower().split()
        return " ".join(self._lemmatize(w) for w in words if w)

    def _normalize_org(self, text: str) -> str:
        """Remove legal forms and normalize organization name."""
        result = text.lower()
        for form in _LEGAL_FORMS:
            result = result.replace(form, "")
        # Strip quotes and extra whitespace
        result = re.sub(r"[«»\"''""„]", "", result)
        return " ".join(result.split()).strip()

    def _lemmatize(self, word: str) -> str:
        """Get the normal (dictionary) form of a word."""
        parsed = self._morph.parse(word)
        if parsed:
            return parsed[0].normal_form
        return word


class EnglishEntityNormalizer:
    """Simple English entity normalizer (lowercase + strip)."""

    def normalize(self, text: str, entity_type: str) -> str:
        """Normalize English entity text."""
        return " ".join(text.lower().strip().split())
