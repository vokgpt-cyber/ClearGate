"""Regression tests for NER pipeline issues found in Alpha v0.1.0.

These tests verify fixes for specific problems observed on the
transport logistics contract screenshot analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.ner_pipeline import NERPipeline

_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def pipeline():
    """Pipeline with spaCy (small) for regression testing."""
    return NERPipeline(
        spacy_model="ru_core_news_sm",
        gliner_model=None,
        enable_llm_layer=False,
    )


class TestInnVsPassportPriority:
    """Issue 4.2: INN detected as passport due to overlapping 10-digit pattern."""

    @pytest.mark.asyncio
    async def test_inn_10_with_context_not_passport(self, pipeline):
        text = "ИНН организации: 7707083893"
        entities = await pipeline.analyze(text)
        matched = [e for e in entities if "7707083893" in e.text]
        assert len(matched) >= 1
        # Should be INN, not passport (passport now requires space in digits)
        assert matched[0].entity_type == "RU_INN"

    @pytest.mark.asyncio
    async def test_passport_with_space_still_works(self, pipeline):
        text = "паспорт серия 4509 123456"
        entities = await pipeline.analyze(text)
        passport = [e for e in entities if e.entity_type == "RU_PASSPORT"]
        assert len(passport) >= 1


class TestOgrnDetection:
    """Issue 4.3: OGRN not being anonymized at all."""

    @pytest.mark.asyncio
    async def test_ogrn_detected(self, pipeline):
        text = "ОГРН 1027700132195"
        entities = await pipeline.analyze(text)
        ogrn = [e for e in entities if e.entity_type == "RU_OGRN"]
        assert len(ogrn) >= 1
        assert "1027700132195" in ogrn[0].text


class TestStopwordFiltering:
    """Issue 4.4, 4.8.4: Legal terms falsely detected as PER/ORG/LOC."""

    @pytest.mark.asyncio
    async def test_legal_roles_not_entities(self, pipeline):
        text = "Исполнитель обязуется оказать Заказчику услуги"
        entities = await pipeline.analyze(text)
        entity_texts = {e.text.lower() for e in entities}
        assert "исполнитель" not in entity_texts
        assert "заказчику" not in entity_texts

    @pytest.mark.asyncio
    async def test_position_not_entity(self, pipeline):
        text = "в лице Генерального директора Иванова Ивана"
        entities = await pipeline.analyze(text)
        entity_texts = {e.text.lower() for e in entities}
        assert "генерального директора" not in entity_texts

    @pytest.mark.asyncio
    async def test_bik_not_org(self, pipeline):
        text = "БИК 044525225"
        entities = await pipeline.analyze(text)
        org_with_bik = [e for e in entities if e.entity_type == "ORG" and "БИК" in e.text]
        assert len(org_with_bik) == 0


class TestPerMerging:
    """Issue 4.5: First name and patronymic split into separate entities."""

    @pytest.mark.asyncio
    async def test_adjacent_per_merged(self, pipeline):
        text = "директора Петрова Алексея Николаевича, действующего"
        entities = await pipeline.analyze(text)
        per_entities = [e for e in entities if e.entity_type == "PER"]
        # All name parts should be merged into one entity
        if per_entities:
            # At minimum, should not have 3 separate PER entities for one name
            assert len(per_entities) <= 2


class TestContractNumber:
    """Issue 4.1: Contract number not anonymized."""

    @pytest.mark.asyncio
    async def test_contract_number_detected(self, pipeline):
        text = "ДОГОВОР ОКАЗАНИЯ УСЛУГ № ТЛ-2026/047"
        entities = await pipeline.analyze(text)
        contract = [e for e in entities if e.entity_type == "RU_CONTRACT_NUMBER"]
        assert len(contract) >= 1


class TestFullContractRegression:
    """Regression test on complete transport contract fixture."""

    @pytest.mark.asyncio
    @pytest.mark.ner
    async def test_transport_contract(self, pipeline):
        text = (_FIXTURES / "transport_contract_regression.txt").read_text(encoding="utf-8")
        expected = json.loads(
            (_FIXTURES / "transport_contract_expected.json").read_text(encoding="utf-8")
        )

        entities = await pipeline.analyze(text)

        # 1. Check expected entities are found
        for exp in expected["expected_entities"]:
            matches = [e for e in entities if exp["text"] in e.text]
            assert len(matches) > 0, (
                f"Expected entity not found: {exp['type']} '{exp['text']}'"
            )

        # 2. Check forbidden texts are not in entities
        for forbidden in expected["must_not_contain"]:
            matches = [e for e in entities if e.text.strip().lower() == forbidden.lower()]
            assert len(matches) == 0, (
                f"Forbidden text found in entities: '{forbidden}'"
            )

        # 3. Check entity count is in reasonable range
        low, high = expected["expected_entity_count_range"]
        assert low <= len(entities) <= high, (
            f"Entity count {len(entities)} outside expected range [{low}, {high}]. "
            f"Entities: {[e.text for e in entities]}"
        )
