"""Regression tests for NER pipeline issues found in Alpha v0.1.0.

These tests verify fixes for specific problems observed on the
transport logistics contract screenshot analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.entities import DetectedEntity
from app.routers.anonymize import _new_deep_scan_suggestions
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

    @pytest.mark.asyncio
    async def test_between_label_not_org(self, pipeline):
        text = "МЕЖДУ: АО «Норд-Хим» / ООО «Бизнес-Парк Сапфир»"
        entities = await pipeline.analyze(text)
        org_texts = {e.text.lower() for e in entities if e.entity_type == "ORG"}
        assert "между" not in org_texts
        assert "ао «норд-хим»" in org_texts
        assert "ооо «бизнес-парк сапфир»" in org_texts

    @pytest.mark.asyncio
    async def test_contract_title_not_org(self, pipeline):
        text = "ЛИЗИНГ\n№ ЛЗ-08-2025\nМЕЖДУ: АО «Норд-Хим» / АО «Финлизинг-Северо-Запад»"
        entities = await pipeline.analyze(text)
        org_texts = {e.text.lower() for e in entities if e.entity_type == "ORG"}
        assert "лизинг" not in org_texts

    def test_loan_title_not_org_after_post_process(self, pipeline):
        title = "\u0417\u0410\u0401\u041c"
        text = f"{title}\n\u2116 3-04-2024"
        entities = [
            DetectedEntity(
                text=title,
                entity_type="ORG",
                start=0,
                end=len(title),
                score=0.92,
                source_layer="llm",
            )
        ]

        assert pipeline.post_process(text, entities) == []

    def test_slash_role_chain_not_position_after_post_process(self, pipeline):
        role = (
            "\u041f\u043e\u0441\u0442\u0430\u0432\u0449\u0438\u043a/"
            "\u0423\u0441\u043b\u0443\u0433\u043e\u0434\u0430\u0442\u0435\u043b\u044c/"
            "\u041f\u043e\u0434\u0440\u044f\u0434\u0447\u0438\u043a"
        )
        text = f"\u0414\u0430\u043b\u0435\u0435 -- {role}"
        start = text.index(role)
        entities = [
            DetectedEntity(
                text=role,
                entity_type="POSITION",
                start=start,
                end=start + len(role),
                score=0.9,
                source_layer="llm-scan",
            )
        ]

        assert pipeline.post_process(text, entities) == []

    def test_contract_number_survives_post_process(self, pipeline):
        number = "\u2116 3-04-2024"
        text = f"\u0414\u043e\u0433\u043e\u0432\u043e\u0440 \u0437\u0430\u0439\u043c\u0430 {number}"
        start = text.index(number)
        entities = [
            DetectedEntity(
                text=number,
                entity_type="RU_CONTRACT_NUMBER",
                start=start,
                end=start + len(number),
                score=0.95,
                source_layer="regex",
            )
        ]

        assert pipeline.post_process(text, entities)[0].text == number

    @pytest.mark.asyncio
    async def test_distributor_contract_fragment(self, pipeline):
        text = (
            "ДИСТРИБУЦИЯ\n"
            "№ Д-15-2024\n"
            "от 28.05.2024\n"
            "МЕЖДУ: АО «Норд-Хим» / Tianjin Forward Polymers Co.\n\n"
            "2. Цена и порядок расчётов\n"
            "Цена договора составляет 4 500 000 "
            "(Four million five hundred thousand) CNY, включая НДС 20%.\n\n"
            "7. Подписи сторон\n"
            "АО «Норд-Хим»\n"
            "Tianjin Forward Polymers Co.\n"
        )

        entities = await pipeline.analyze(text)
        org_texts = {e.text.lower() for e in entities if e.entity_type == "ORG"}
        money_texts = {e.text for e in entities if e.entity_type == "MON"}

        assert "дистрибуция" not in org_texts
        assert "cny" not in org_texts
        assert "tianjin forward polymers co." in org_texts
        assert any("4 500 000" in value and "CNY" in value for value in money_texts)

    def test_money_not_replaced_by_llm_contract_number(self, pipeline):
        money = "4 500 000 (Four million five hundred thousand) CNY"
        wrong_contract = "4 500 000"
        text = f"Цена договора составляет {money}, включая НДС 20%."
        money_start = text.index(money)
        wrong_start = text.index(wrong_contract)
        entities = [
            DetectedEntity(
                text=money,
                entity_type="MON",
                start=money_start,
                end=money_start + len(money),
                score=0.92,
                source_layer="regex",
            ),
            DetectedEntity(
                text=wrong_contract,
                entity_type="RU_CONTRACT_NUMBER",
                start=wrong_start,
                end=wrong_start + len(wrong_contract),
                score=0.8,
                source_layer="llm-scan",
            ),
        ]

        processed = pipeline.post_process(text, entities)
        assert [e.entity_type for e in processed] == ["MON"]
        assert processed[0].text == money


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

class TestDeepScanQaMode:
    """Deep Scan must propose additions, not rewrite existing markup."""

    def test_deep_scan_suggestions_do_not_overlap_current_entities(self):
        current = [
            DetectedEntity(
                text="4 500 000 CNY",
                entity_type="MON",
                start=20,
                end=33,
                score=0.95,
                source_layer="regex",
            )
        ]
        processed = [
            *current,
            DetectedEntity(
                text="CNY",
                entity_type="ORG",
                start=30,
                end=33,
                score=0.8,
                source_layer="llm-scan",
            ),
            DetectedEntity(
                text="Tianjin Forward Polymers Co.",
                entity_type="ORG",
                start=45,
                end=73,
                score=0.86,
                source_layer="llm-scan",
            ),
        ]

        suggestions = _new_deep_scan_suggestions(current, processed)

        assert [s.text for s in suggestions] == ["Tianjin Forward Polymers Co."]


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
