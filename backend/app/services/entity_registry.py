"""EntityRegistry — consistent PII placeholder mapping with encryption.

Maps real entities to stable placeholders ([ЛИЦО_1], [ОРГАНИЗАЦИЯ_1], etc.)
with Russian morphological awareness and AES-256-GCM encryption at rest.

This is the core anonymization state — the mapping table is the most
sensitive data in the entire system.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from Levenshtein import distance as levenshtein_distance
from pydantic import BaseModel, Field

from app.models.entities import DetectedEntity
from app.services.crypto import CryptoService
from app.services.entity_normalizer import EnglishEntityNormalizer, RussianEntityNormalizer

logger = structlog.get_logger(__name__)


class MappingEntry(BaseModel):
    """A single entry in the entity mapping table."""

    placeholder: str
    canonical_value: str
    original_forms: list[str] = Field(default_factory=list)
    entity_type: str


# Type labels for placeholder generation
_RU_LABELS: dict[str, str] = {
    "PER": "ЛИЦО",
    "ORG": "ОРГАНИЗАЦИЯ",
    "LOC": "МЕСТО",
    "ADDR": "АДРЕС",
    "MON": "СУММА",
    "DATE": "ДАТА",
    "RU_INN": "ИНН",
    "RU_OGRN": "ОГРН",
    "RU_SNILS": "СНИЛС",
    "RU_PASSPORT": "ПАСПОРТ",
    "RU_BANK_ACCOUNT": "СЧЁТ",
    "RU_PHONE": "ТЕЛЕФОН",
    "RU_DATE": "ДАТА",
    "EMAIL_ADDRESS": "EMAIL",
    "RU_CASE_NUMBER": "ДЕЛО",
    "RU_CONTRACT_NUMBER": "ДОГОВОР",
    "POSITION": "ДОЛЖНОСТЬ",
    "PROJECT_CODENAME": "ПРОЕКТ",
}

_EN_LABELS: dict[str, str] = {
    "PER": "PERSON",
    "ORG": "ORG",
    "LOC": "LOCATION",
    "ADDR": "ADDRESS",
    "MON": "AMOUNT",
    "DATE": "DATE",
    "RU_INN": "INN",
    "RU_OGRN": "OGRN",
    "RU_SNILS": "SNILS",
    "RU_PASSPORT": "PASSPORT",
    "RU_BANK_ACCOUNT": "ACCOUNT",
    "RU_PHONE": "PHONE",
    "RU_DATE": "DATE",
    "EMAIL_ADDRESS": "EMAIL",
    "RU_CASE_NUMBER": "CASE",
    "RU_CONTRACT_NUMBER": "CONTRACT",
    "POSITION": "POSITION",
    "PROJECT_CODENAME": "PROJECT",
}


class EntityRegistry:
    """In-memory registry mapping real entities to anonymized placeholders.

    Provides consistent placeholder assignment with Russian morphological
    awareness. Mapping table is encrypted with AES-256-GCM at rest.

    NOT thread-safe — one registry per session.

    Args:
        master_key: 32-byte AES master key.
        session_id: Unique session identifier for key derivation.
        locale: "ru" or "en" for placeholder labels.

    Examples:
        >>> import secrets
        >>> registry = EntityRegistry(secrets.token_bytes(32), "session-1")
        >>> entity = DetectedEntity(text="Иванов", entity_type="PER", start=0, end=6, score=0.9)
        >>> placeholder = registry.get_or_create_placeholder(entity)
        >>> placeholder
        '[ЛИЦО_1]'
    """

    def __init__(
        self,
        master_key: bytes,
        session_id: str,
        locale: Literal["ru", "en"] = "ru",
    ) -> None:
        self.session_id = session_id
        self.locale = locale
        self._crypto = CryptoService(master_key)
        self._counters: dict[str, int] = {}
        self._mapping: dict[str, MappingEntry] = {}  # canonical → entry
        self._reverse: dict[str, MappingEntry] = {}  # placeholder → entry
        self._normalizer = (
            RussianEntityNormalizer() if locale == "ru" else EnglishEntityNormalizer()
        )
        self._labels = _RU_LABELS if locale == "ru" else _EN_LABELS

    def get_or_create_placeholder(self, entity: DetectedEntity) -> str:
        """Get existing placeholder or create a new one for an entity.

        Performs normalization (pymorphy3 for Russian) and fuzzy matching
        (Levenshtein) to find existing entries for inflected forms.
        """
        canonical = self._normalizer.normalize(entity.text, entity.entity_type)

        # Exact match
        if canonical in self._mapping:
            entry = self._mapping[canonical]
            if entity.text not in entry.original_forms:
                entry.original_forms.append(entity.text)
            return entry.placeholder

        # Fuzzy match
        fuzzy_match = self._fuzzy_lookup(canonical, entity.entity_type)
        if fuzzy_match:
            if entity.text not in fuzzy_match.original_forms:
                fuzzy_match.original_forms.append(entity.text)
            # Also register canonical form for future exact matches
            self._mapping[canonical] = fuzzy_match
            return fuzzy_match.placeholder

        # New entity
        return self._create_new_entry(entity, canonical)

    def anonymize_text(self, text: str, entities: list[DetectedEntity]) -> str:
        """Replace all entity occurrences with placeholders.

        Entities are processed in reverse order to preserve character offsets.
        """
        sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
        result = text
        for entity in sorted_entities:
            placeholder = self.get_or_create_placeholder(entity)
            result = result[:entity.start] + placeholder + result[entity.end:]
        return result

    def deanonymize_text(self, text: str) -> str:
        """Replace all placeholders in text with original (canonical) values."""
        result = text
        # Sort by placeholder length descending to avoid partial replacements
        for placeholder in sorted(self._reverse, key=len, reverse=True):
            entry = self._reverse[placeholder]
            result = result.replace(placeholder, entry.canonical_value)
        return result

    def update_entity(self, placeholder: str, new_canonical: str) -> None:
        """User-driven correction during review."""
        if placeholder not in self._reverse:
            raise KeyError(f"Placeholder {placeholder} not in registry")
        entry = self._reverse[placeholder]
        old_canonical = entry.canonical_value
        entry.canonical_value = new_canonical
        del self._mapping[old_canonical]
        self._mapping[new_canonical] = entry

    def export_encrypted(self) -> bytes:
        """Serialize and encrypt mapping table with AES-256-GCM."""
        data: dict[str, Any] = {
            "session_id": self.session_id,
            "locale": self.locale,
            "counters": self._counters,
            "entries": [e.model_dump() for e in self._mapping.values()],
        }
        return self._crypto.encrypt_mapping(data, self.session_id)

    def import_encrypted(self, blob: bytes) -> None:
        """Restore registry state from an encrypted blob."""
        data = self._crypto.decrypt_mapping(blob, self.session_id)
        self._counters = data.get("counters", {})
        self._mapping.clear()
        self._reverse.clear()
        for entry_data in data.get("entries", []):
            entry = MappingEntry(**entry_data)
            self._mapping[entry.canonical_value] = entry
            self._reverse[entry.placeholder] = entry

    def get_all_entries(self) -> list[MappingEntry]:
        """Return all mapping entries (for UI display)."""
        return list(self._mapping.values())

    @property
    def entity_count(self) -> int:
        """Total number of unique entities in the registry."""
        return len(self._reverse)

    def clear(self) -> None:
        """Securely zero out all sensitive data."""
        for entry in list(self._mapping.values()):
            entry.canonical_value = "\x00" * len(entry.canonical_value)
            entry.original_forms.clear()
        self._mapping.clear()
        self._reverse.clear()
        self._counters.clear()
        logger.info("entity_registry.cleared", session_id=self.session_id)

    # Internal methods

    def _fuzzy_lookup(self, canonical: str, entity_type: str) -> MappingEntry | None:
        """Find similar existing entry using Levenshtein distance."""
        max_dist = 2 if len(canonical) < 20 else 4
        candidates = [e for e in self._mapping.values() if e.entity_type == entity_type]
        for entry in candidates:
            if levenshtein_distance(canonical, entry.canonical_value) <= max_dist:
                return entry
        return None

    def _create_new_entry(self, entity: DetectedEntity, canonical: str) -> str:
        """Create a new mapping entry and return its placeholder."""
        counter = self._counters.get(entity.entity_type, 0) + 1
        self._counters[entity.entity_type] = counter

        label = self._labels.get(entity.entity_type, entity.entity_type)
        placeholder = f"[{label}_{counter}]"

        entry = MappingEntry(
            placeholder=placeholder,
            canonical_value=canonical,
            original_forms=[entity.text],
            entity_type=entity.entity_type,
        )
        self._mapping[canonical] = entry
        self._reverse[placeholder] = entry

        logger.info(
            "entity_registry.new_entry",
            placeholder=placeholder,
            entity_type=entity.entity_type,
        )
        return placeholder
