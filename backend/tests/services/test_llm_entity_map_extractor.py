"""Tests for strict Gemma entity-map validation.

These tests do not call a real LLM. They exercise the local safety contract:
only spans that point back to exact source text may enter the anonymization
pipeline.
"""

from __future__ import annotations

from app.services.llm_entity_map_extractor import LLMEntityMapExtractor, TextChunk


def test_validated_entity_requires_exact_source_span() -> None:
    text = "МЕЖДУ: АО «Норд-Хим» и Meridian Advisory LLC."
    chunk = TextChunk(text=text, start=0, index=0)
    extractor = LLMEntityMapExtractor()
    start = text.index("АО «Норд-Хим»")

    entity = extractor._validated_entity(
        text,
        chunk,
        {
            "text": "АО «Норд-Хим»",
            "entity_type": "ORG",
            "start": start,
            "end": start + len("АО «Норд-Хим»"),
            "score": 0.94,
            "action": "auto",
        },
    )

    assert entity is not None
    assert entity.text == "АО «Норд-Хим»"
    assert entity.entity_type == "ORG"
    assert entity.source_layer == "llm-map"


def test_validated_entity_drops_hallucinated_text() -> None:
    text = "МЕЖДУ: АО «Норд-Хим» и Meridian Advisory LLC."
    chunk = TextChunk(text=text, start=0, index=0)
    extractor = LLMEntityMapExtractor()

    entity = extractor._validated_entity(
        text,
        chunk,
        {
            "text": "ООО «Не существует»",
            "entity_type": "ORG",
            "start": 8,
            "end": 28,
            "score": 0.94,
            "action": "auto",
        },
    )

    assert entity is None


def test_validated_entity_repairs_unique_nearby_offset_only() -> None:
    text = "Цена договора 1 562 500 рублей. ИНН: 7801456328."
    chunk = TextChunk(text=text, start=0, index=0)
    extractor = LLMEntityMapExtractor()

    entity = extractor._validated_entity(
        text,
        chunk,
        {
            "text": "1 562 500 рублей",
            "entity_type": "MON",
            "start": 0,
            "end": 15,
            "score": 0.9,
            "action": "auto",
        },
    )

    assert entity is not None
    assert entity.start == text.index("1 562 500 рублей")
    assert entity.metadata["llm_entity_map_realigned"] is True
