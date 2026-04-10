"""Tests for EntityRegistry."""

import secrets

import pytest

from app.models.entities import DetectedEntity
from app.services.entity_registry import EntityRegistry


@pytest.fixture()
def master_key():
    return secrets.token_bytes(32)


@pytest.fixture()
def registry(master_key):
    return EntityRegistry(master_key, "test-session", locale="ru")


def _entity(text, entity_type="PER", start=0, end=None, score=0.9):
    """Helper to create test entities."""
    return DetectedEntity(
        text=text,
        entity_type=entity_type,
        start=start,
        end=end or len(text),
        score=score,
    )


class TestBasicOperations:
    def test_create_placeholder(self, registry):
        entity = _entity("Иванов")
        placeholder = registry.get_or_create_placeholder(entity)
        assert placeholder.startswith("[ЛИЦО_")
        assert placeholder.endswith("]")

    def test_same_entity_same_placeholder(self, registry):
        e1 = _entity("Иванов")
        e2 = _entity("Иванов")
        p1 = registry.get_or_create_placeholder(e1)
        p2 = registry.get_or_create_placeholder(e2)
        assert p1 == p2

    def test_different_entities_different_placeholders(self, registry):
        e1 = _entity("Иванов")
        e2 = _entity("Сидорова")
        p1 = registry.get_or_create_placeholder(e1)
        p2 = registry.get_or_create_placeholder(e2)
        assert p1 != p2

    def test_counter_increments(self, registry):
        p1 = registry.get_or_create_placeholder(_entity("Иванов"))
        p2 = registry.get_or_create_placeholder(_entity("Петров"))
        assert "[ЛИЦО_1]" == p1
        assert "[ЛИЦО_2]" == p2

    def test_different_types(self, registry):
        p1 = registry.get_or_create_placeholder(_entity("Иванов", "PER"))
        p2 = registry.get_or_create_placeholder(_entity("Ромашка", "ORG"))
        assert "ЛИЦО" in p1
        assert "ОРГАНИЗАЦИЯ" in p2

    def test_entity_count(self, registry):
        registry.get_or_create_placeholder(_entity("Иванов"))
        registry.get_or_create_placeholder(_entity("Петров"))
        assert registry.entity_count == 2


class TestAnonymizeDeAnonymize:
    def test_anonymize_text(self, registry):
        text = "Иванов подписал договор"
        entities = [_entity("Иванов", start=0, end=6)]
        result = registry.anonymize_text(text, entities)
        assert "Иванов" not in result
        assert "[ЛИЦО_1]" in result

    def test_deanonymize_text(self, registry):
        entity = _entity("Иванов", start=0, end=6)
        registry.get_or_create_placeholder(entity)
        anon = "[ЛИЦО_1] подписал договор"
        result = registry.deanonymize_text(anon)
        assert "[ЛИЦО_1]" not in result

    def test_roundtrip(self, registry):
        text = "Иванов подписал договор с Петровым"
        entities = [
            _entity("Иванов", start=0, end=6),
            _entity("Петровым", start=25, end=33),
        ]
        anonymized = registry.anonymize_text(text, entities)
        assert "Иванов" not in anonymized
        assert "Петровым" not in anonymized
        # Deanonymize restores canonical forms (may differ from original inflection)
        deanonymized = registry.deanonymize_text(anonymized)
        assert "[ЛИЦО_" not in deanonymized


class TestFuzzyMatching:
    def test_levenshtein_close_match(self, registry):
        e1 = _entity("7707083893", "RU_INN")
        e2 = _entity("7707083894", "RU_INN")  # 1 char different
        p1 = registry.get_or_create_placeholder(e1)
        p2 = registry.get_or_create_placeholder(e2)
        # Levenshtein distance = 1, should match
        assert p1 == p2

    def test_levenshtein_too_far(self, registry):
        e1 = _entity("Иванов", "PER")
        e2 = _entity("Сидоров", "PER")  # completely different
        p1 = registry.get_or_create_placeholder(e1)
        p2 = registry.get_or_create_placeholder(e2)
        assert p1 != p2


class TestEncryption:
    def test_export_import_roundtrip(self, registry, master_key):
        registry.get_or_create_placeholder(_entity("Иванов"))
        registry.get_or_create_placeholder(_entity("Ромашка", "ORG"))

        blob = registry.export_encrypted()
        assert isinstance(blob, bytes)
        assert len(blob) > 0

        # Import into a new registry
        new_registry = EntityRegistry(master_key, "test-session", locale="ru")
        new_registry.import_encrypted(blob)
        assert new_registry.entity_count == 2

    def test_wrong_key_fails_import(self, registry):
        registry.get_or_create_placeholder(_entity("Иванов"))
        blob = registry.export_encrypted()

        wrong_key = secrets.token_bytes(32)
        new_registry = EntityRegistry(wrong_key, "test-session", locale="ru")
        with pytest.raises(Exception):  # InvalidTag
            new_registry.import_encrypted(blob)


class TestUpdateAndClear:
    def test_update_entity(self, registry):
        registry.get_or_create_placeholder(_entity("Иванов"))
        registry.update_entity("[ЛИЦО_1]", "петров")
        result = registry.deanonymize_text("[ЛИЦО_1] подписал")
        assert "петров" in result

    def test_update_nonexistent_raises(self, registry):
        with pytest.raises(KeyError):
            registry.update_entity("[ЛИЦО_99]", "test")

    def test_clear(self, registry):
        registry.get_or_create_placeholder(_entity("Иванов"))
        assert registry.entity_count == 1
        registry.clear()
        assert registry.entity_count == 0


class TestEnglishLocale:
    def test_english_labels(self, master_key):
        registry = EntityRegistry(master_key, "test", locale="en")
        p = registry.get_or_create_placeholder(_entity("John Smith"))
        assert "PERSON" in p
