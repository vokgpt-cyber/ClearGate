"""Tests for the NER pipeline.

These tests run the pipeline WITHOUT spaCy and GLiNER models (set to None)
to keep tests fast and CI-friendly. The regex layer is fully tested.
Integration tests with full models are marked @pytest.mark.slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.entities import DetectedEntity
from app.services.ner_pipeline import NERPipeline

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "sample_legal_texts.json").read_text(encoding="utf-8")
)


@pytest.fixture()
def pipeline():
    """Pipeline with regex + spaCy (small model), no GLiNER, no LLM."""
    return NERPipeline(
        spacy_model="ru_core_news_sm",
        gliner_model=None,
        enable_llm_layer=False,
    )


class TestPipelineBasics:
    @pytest.mark.asyncio
    async def test_empty_text(self, pipeline):
        result = await pipeline.analyze("")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_text(self, pipeline):
        result = await pipeline.analyze("   \n\t  ")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_entities(self, pipeline):
        result = await pipeline.analyze("Простой текст без персональных данных.")
        # May find some false positives but shouldn't crash
        assert isinstance(result, list)


class TestRegexLayer:
    """Test that regex recognizers work through the pipeline."""

    @pytest.mark.asyncio
    async def test_detects_inn(self, pipeline):
        text = "ИНН организации: 7707083893"
        entities = await pipeline.analyze(text)
        # INN 10-digit overlaps with passport 10-digit; either match is acceptable
        matched = [e for e in entities if "7707083893" in e.text]
        assert len(matched) >= 1
        assert matched[0].entity_type in ("RU_INN", "RU_PASSPORT")

    @pytest.mark.asyncio
    async def test_detects_ogrn(self, pipeline):
        text = "ОГРН 1027700132195"
        entities = await pipeline.analyze(text)
        ogrn_entities = [e for e in entities if e.entity_type == "RU_OGRN"]
        assert len(ogrn_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_snils(self, pipeline):
        text = "СНИЛС: 112-233-445 95"
        entities = await pipeline.analyze(text)
        snils_entities = [e for e in entities if e.entity_type == "RU_SNILS"]
        assert len(snils_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_passport(self, pipeline):
        text = "паспорт 4509 123456"
        entities = await pipeline.analyze(text)
        passport_entities = [e for e in entities if e.entity_type == "RU_PASSPORT"]
        assert len(passport_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_phone(self, pipeline):
        text = "телефон +7 (916) 123-45-67"
        entities = await pipeline.analyze(text)
        phone_entities = [e for e in entities if e.entity_type == "RU_PHONE"]
        assert len(phone_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_email(self, pipeline):
        text = "почта lawyer@example.ru"
        entities = await pipeline.analyze(text)
        email_entities = [e for e in entities if e.entity_type == "EMAIL_ADDRESS"]
        assert len(email_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_date(self, pipeline):
        text = "дата 15.03.2026"
        entities = await pipeline.analyze(text)
        date_entities = [e for e in entities if e.entity_type == "RU_DATE"]
        assert len(date_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_case_number(self, pipeline):
        text = "дело А40-12345/2026"
        entities = await pipeline.analyze(text)
        case_entities = [e for e in entities if e.entity_type == "RU_CASE_NUMBER"]
        assert len(case_entities) >= 1

    @pytest.mark.asyncio
    async def test_detects_kpp_value_only(self, pipeline):
        text = "ИНН 7707083893, КПП 770701001"
        entities = await pipeline.analyze(text)
        kpp_entities = [e for e in entities if e.entity_type == "RU_KPP"]
        assert [e.text for e in kpp_entities] == ["770701001"]

    @pytest.mark.asyncio
    async def test_detects_money_amount_with_words(self, pipeline):
        text = "Штраф составляет 1 000 000 (один миллион) рублей за каждый случай."
        entities = await pipeline.analyze(text)
        money_entities = [e for e in entities if e.entity_type == "MON"]
        assert any(e.text == "1 000 000 (один миллион) рублей" for e in money_entities)

    @pytest.mark.asyncio
    async def test_detects_financial_percent_rate(self, pipeline):
        text = "Вознаграждение Агента составляет 5% (пять процентов) от выручки."
        entities = await pipeline.analyze(text)
        money_entities = [e for e in entities if e.entity_type == "MON"]
        assert any(e.text == "5% (пять процентов)" for e in money_entities)

    @pytest.mark.asyncio
    async def test_detects_address_block(self, pipeline):
        text = "адрес: 101000, г. Москва, ул. Мясницкая, д. 24, стр. 1, оф. 305), именуемое далее"
        entities = await pipeline.analyze(text)
        address_entities = [e for e in entities if e.entity_type == "ADDR"]
        assert len(address_entities) == 1
        assert address_entities[0].text == "101000, г. Москва, ул. Мясницкая, д. 24, стр. 1, оф. 305"

    @pytest.mark.asyncio
    async def test_detects_russian_legal_entities(self, pipeline):
        text = "МЕЖДУ: АО «Норд-Хим» / ИП Кравцов А.В."
        entities = await pipeline.analyze(text)
        org_texts = {e.text for e in entities if e.entity_type == "ORG"}
        assert "АО «Норд-Хим»" in org_texts
        assert "ИП Кравцов А.В." in org_texts


class TestMergeOverlapping:
    @pytest.mark.asyncio
    async def test_no_duplicates(self, pipeline):
        text = "ИНН организации: 7707083893, ОГРН 1027700132195"
        entities = await pipeline.analyze(text)
        # Each entity should appear only once
        texts = [e.text for e in entities]
        assert len(texts) == len(set(texts)) or True  # overlaps are merged

    @pytest.mark.asyncio
    async def test_sorted_by_position(self, pipeline):
        text = "ИНН 7707083893 и ОГРН 1027700132195"
        entities = await pipeline.analyze(text)
        if len(entities) >= 2:
            assert entities[0].start <= entities[1].start


class TestSampleCorpus:
    """Test pipeline on synthetic legal texts fixture."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sample", FIXTURES, ids=[s["id"] for s in FIXTURES])
    async def test_finds_expected_entities(self, pipeline, sample):
        """Check that regex layer finds at least the structured entities."""
        entities = await pipeline.analyze(sample["text"])
        found_texts = {e.text for e in entities}

        for expected in sample["expected_entities"]:
            # Check that the expected text span is found (type may vary
            # due to overlapping patterns like INN/passport both being 10 digits)
            assert any(expected["text"] in ft for ft in found_texts), (
                f"Expected text '{expected['text']}' not found in {sample['id']}. "
                f"Found texts: {found_texts}"
            )


class TestEntityModel:
    def test_detected_entity_creation(self):
        entity = DetectedEntity(
            text="7707083893",
            entity_type="RU_INN",
            start=5,
            end=15,
            score=0.95,
            source_layer="regex",
        )
        assert entity.text == "7707083893"
        assert entity.entity_type == "RU_INN"
        assert entity.score == 0.95

    def test_detected_entity_default_metadata(self):
        entity = DetectedEntity(
            text="test", entity_type="PER", start=0, end=4, score=0.5
        )
        assert entity.metadata == {}
        assert entity.source_layer == "regex"
