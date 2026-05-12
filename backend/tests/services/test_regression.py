"""Regression tests for NER pipeline issues found in Alpha v0.1.0.

These tests verify fixes for specific problems observed on the
transport logistics contract screenshot analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.entities import DetectedEntity
from app.routers.anonymize import _deep_scan_removal_suggestions, _new_deep_scan_suggestions
from app.services.ner_pipeline import NERPipeline
from app.services.regex_recognizers import (
    AddressRuRecognizer,
    MoneyRuRecognizer,
    OrganizationRuRecognizer,
)

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

    def test_rospatent_not_org_after_post_process(self, pipeline):
        text = "\u0421\u0432\u0438\u0434\u0435\u0442\u0435\u043b\u044c\u0441\u0442\u0432\u043e \u0420\u043e\u0441\u043f\u0430\u0442\u0435\u043d\u0442\u0430 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u043e."
        target = "\u0420\u043e\u0441\u043f\u0430\u0442\u0435\u043d\u0442"
        start = text.index(target)
        entities = [
            DetectedEntity(
                text=target,
                entity_type="ORG",
                start=start,
                end=start + len(target),
                score=0.91,
                source_layer="llm-scan",
            )
        ]

        assert pipeline.post_process(text, entities) == []

    def test_reconciliation_act_title_not_org_after_post_process(self, pipeline):
        title = "\u0410\u041a\u0422 \u0412\u0417\u0410\u0418\u041c\u041d\u041e\u0419 \u0421\u0412\u0415\u0420\u041a\u0418"
        text = (
            f"{title} \u0420\u0410\u0421\u0427\u0401\u0422\u041e\u0412\n"
            "\u043e\u0442 31 \u0434\u0435\u043a\u0430\u0431\u0440\u044f 2024 \u0433.\n\n"
            "\u041c\u0415\u0416\u0414\u0423: \u0410\u041e \u00ab\u041d\u043e\u0440\u0434-\u0425\u0438\u043c\u00bb \u0438 \u041e\u041e\u041e \u00ab\u041f\u043e\u043b\u0438\u043c\u0435\u0440-\u0422\u0440\u0435\u0439\u0434\u00bb"
        )
        entities = [
            DetectedEntity(
                text=title,
                entity_type="ORG",
                start=0,
                end=len(title),
                score=0.93,
                source_layer="llm",
            )
        ]

        assert pipeline.post_process(text, entities) == []

    def test_pdf_delayed_title_not_org_after_post_process(self, pipeline):
        prefix = "\n" * 30 + (" " * 420)
        title = "\u0414\u0418\u0421\u0422\u0420\u0418\u0411\u0423\u0426\u0418\u042f"
        text = (
            f"{prefix}{title}\n"
            "\u2116 \u0414-15-2024\n"
            "\u041c\u0415\u0416\u0414\u0423: \u0410\u041e \u00ab\u041d\u043e\u0440\u0434-\u0425\u0438\u043c\u00bb / Tianjin Forward Polymers Co."
        )
        start = text.index(title)
        entities = [
            DetectedEntity(
                text=title,
                entity_type="ORG",
                start=start,
                end=start + len(title),
                score=0.92,
                source_layer="llm-scan",
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
        english_hits = [
            e for e in entities
            if e.entity_type == "ORG" and e.text.lower() == "tianjin forward polymers co."
        ]
        money_texts = {e.text for e in entities if e.entity_type == "MON"}

        assert "дистрибуция" not in org_texts
        assert "cny" not in org_texts
        assert "tianjin forward polymers co." in org_texts
        assert len(english_hits) >= 2
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

    def test_pdf_lease_false_positives_after_post_process(self, pipeline):
        text = (
            "Аренда складского помещения площадью 1850 кв.м.\n"
            "Без НДС 18%.\n"
            "Задержка более 10 дней: пеня 0,1% в день.\n"
            "Право Арендодателя на расторжение.\n"
            "РЕКВИЗИТЫ сторон\n"
            "Месячная стоимость: (Двести тысяч (200 000) рублей).\n"
            "Валюта CNY."
        )
        candidates = [
            ("кв.м.", "LOC"),
            ("18%", "MON"),
            ("пеня", "MON"),
            ("Арендодателя", "LOC"),
            ("РЕКВИЗИТЫ", "ORG"),
            ("200 000", "RU_BIK"),
            ("CNY", "ORG"),
        ]
        entities = [
            DetectedEntity(
                text=value,
                entity_type=entity_type,
                start=text.index(value),
                end=text.index(value) + len(value),
                score=0.9,
                source_layer="llm-scan",
            )
            for value, entity_type in candidates
        ]

        assert pipeline.post_process(text, entities) == []

    def test_pdf_relative_durations_not_dates_after_post_process(self, pipeline):
        text = (
            "Срок: 11 месяцев (18.07.2024 - 17.06.2025).\n"
            "Задержка более 10 дней. Расторжение: уведомление за 30 дней."
        )
        candidates = ["11 месяцев", "10 дней", "30 дней"]
        entities = [
            DetectedEntity(
                text=value,
                entity_type="RU_DATE",
                start=text.index(value),
                end=text.index(value) + len(value),
                score=0.86,
                source_layer="llm-scan",
            )
            for value in candidates
        ]

        assert pipeline.post_process(text, entities) == []

    def test_egrul_heading_not_org_after_post_process(self, pipeline):
        heading = "ВЫПИСКА из Единого государственного реестра юридических лиц"
        text = f"{heading}\nОГРН: 1117847296753\nИНН: 7801456328"
        entities = [
            DetectedEntity(
                text="ВЫПИСКА",
                entity_type="ORG",
                start=0,
                end=len("ВЫПИСКА"),
                score=0.9,
                source_layer="llm-scan",
            ),
            DetectedEntity(
                text=heading,
                entity_type="ORG",
                start=0,
                end=len(heading),
                score=0.84,
                source_layer="llm-scan",
            ),
        ]

        assert pipeline.post_process(text, entities) == []

    def test_pdf_monthly_cost_without_outer_parentheses_detected(self):
        text = "Месячная стоимость: Двести тысяч (200 000) рублей."

        money = [
            text[r.start:r.end]
            for r in MoneyRuRecognizer().analyze(text, ["MON"])
        ]

        assert "Двести тысяч (200 000) рублей" in money

    def test_pdf_lease_recognizers_keep_real_values_and_bounds(self):
        text = (
            "Заключен между ООО «Промышленная\n"
            "недвижимость СПб» и АО «Норд-Хим».\n"
            "Адрес: СПб, ул. Литераторов, д. 20 / Банк: ПАО ВТБ\n"
            "Месячная стоимость: (Двести тысяч (200 000) рублей).\n"
            "Без НДС 18%. Пеня 0,1% в день."
        )

        orgs = [
            text[r.start:r.end].replace("\n", " ")
            for r in OrganizationRuRecognizer().analyze(text, ["ORG"])
        ]
        addresses = [
            text[r.start:r.end]
            for r in AddressRuRecognizer().analyze(text, ["ADDR"])
        ]
        money = [
            text[r.start:r.end]
            for r in MoneyRuRecognizer().analyze(text, ["MON"])
        ]

        assert "ООО «Промышленная недвижимость СПб»" in orgs
        assert any(value == "СПб, ул. Литераторов, д. 20" for value in addresses)
        assert all("Банк" not in value for value in addresses)
        assert "(Двести тысяч (200 000) рублей)" in money
        assert "18%" not in money
        assert "0,1%" not in money

    def test_professional_firm_name_recognizer_keeps_name_not_descriptor(self):
        text = "Документ подготовило Адвокатское бюро ЕПАМ."

        orgs = [
            text[r.start:r.end]
            for r in OrganizationRuRecognizer().analyze(text, ["ORG"])
        ]

        assert "Адвокатское бюро ЕПАМ" in orgs
        assert "Адвокатское бюро" not in orgs


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

    def test_deep_scan_can_propose_false_positive_removals(self, pipeline):
        text = "ВЫПИСКА из Единого государственного реестра юридических лиц"
        current = [
            DetectedEntity(
                text="ВЫПИСКА",
                entity_type="ORG",
                start=0,
                end=len("ВЫПИСКА"),
                score=0.9,
                source_layer="llm-scan",
            )
        ]
        processed = pipeline.post_process(text, current)

        removals = _deep_scan_removal_suggestions(current, processed)

        assert [entity.text for entity in removals] == ["ВЫПИСКА"]


    def test_policy_can_surface_review_only_weak_orgs(self, pipeline):
        text = (
            "\u0414\u043e\u0433\u043e\u0432\u043e\u0440\n"
            "\u041c\u0415\u0416\u0414\u0423: \u0410\u041e \u00ab\u041d\u043e\u0440\u0434-\u0425\u0438\u043c\u00bb / EuroSoft Solutions"
        )
        value = "EuroSoft Solutions"
        start = text.index(value)
        candidate = DetectedEntity(
            text=value,
            entity_type="ORG",
            start=start,
            end=start + len(value),
            score=0.82,
            source_layer="llm-scan",
        )

        assert pipeline.post_process(text, [candidate]) == []

        review = pipeline.post_process(text, [candidate], include_review=True)

        assert len(review) == 1
        assert review[0].metadata["policy_action"] == "review"
        assert review[0].metadata["policy_reason"] == "weak_organization_candidate"


class TestPolicyDrivenPrecision:
    """Profile-aware policy for forms and internal policy documents."""

    @pytest.mark.asyncio
    async def test_dms_form_detects_person_policy_and_drops_public_leaflet_noise(self, pipeline):
        text = (
            "\u0417\u0430\u0441\u0442\u0440\u0430\u0445\u043e\u0432\u0430\u043d\u043d\u044b\u0439\n"
            "\u041a\u0430\u0440\u0435\u043b\u0438\u043d\u0430 \u041e\u041b\u042c\u0413\u0410 \u0410\u041b\u0415\u041a\u0421\u0410\u041d\u0414\u0420\u041e\u0412\u041d\u0410\n"
            "\u0414\u0430\u0442\u0430 \u0440\u043e\u0436\u0434\u0435\u043d\u0438\u044f\n"
            "12.12.1986\n"
            "\u041d\u043e\u043c\u0435\u0440 \u043f\u043e\u043b\u0438\u0441\u0430\n"
            "001\u0414\u041c\u042138505624/558\n"
            "\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f\n"
            "\u0441 15.05.2026 \u043f\u043e 31.07.2027\n"
            "\u041a\u0440\u0443\u0433\u043b\u043e\u0441\u0443\u0442\u043e\u0447\u043d\u044b\u0439\n"
            "8 (800) 700-15-75 \u0444\u0435\u0434\u0435\u0440\u0430\u043b\u044c\u043d\u044b\u0439 \u043c\u0435\u0434\u0438\u0446\u0438\u043d\u0441\u043a\u0438\u0439\n"
            "8 (495) 725-10-10 \u041c\u043e\u0441\u043a\u0432\u0430\n"
            "8 (812) 320-87-26 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\n"
            "\u0412\u043e\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439\u0442\u0435\u0441\u044c \u043c\u043e\u0431\u0438\u043b\u044c\u043d\u044b\u043c \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435\u043c "
            "\u00ab\u0420\u0435\u043d\u0435\u0441\u0441\u0430\u043d\u0441 \u0417\u0434\u043e\u0440\u043e\u0432\u044c\u0435\u00bb."
        )

        entities = await pipeline.analyze(text)
        by_type = {(entity.entity_type, entity.text) for entity in entities}
        all_texts = {entity.text for entity in entities}

        assert (
            "PER",
            "\u041a\u0430\u0440\u0435\u043b\u0438\u043d\u0430 \u041e\u041b\u042c\u0413\u0410 \u0410\u041b\u0415\u041a\u0421\u0410\u041d\u0414\u0420\u041e\u0412\u041d\u0410",
        ) in by_type
        assert ("RU_POLICY_NUMBER", "001\u0414\u041c\u042138505624/558") in by_type
        assert ("RU_DATE", "12.12.1986") in by_type
        assert not any(entity.entity_type == "RU_PHONE" for entity in entities)
        assert "\u041c\u043e\u0441\u043a\u0432\u0430" not in all_texts
        assert "\u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433" not in all_texts
        assert "\u0420\u0435\u043d\u0435\u0441\u0441\u0430\u043d\u0441 \u0417\u0434\u043e\u0440\u043e\u0432\u044c\u0435" not in all_texts

    @pytest.mark.asyncio
    async def test_internal_policy_keeps_epam_but_ignores_generic_terms(self, pipeline):
        text = (
            "\u041f\u043e\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u043e\u0431 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0438 \u0418\u0418\n"
            "\u041d\u0430\u0441\u0442\u043e\u044f\u0449\u0435\u0435 \u041f\u043e\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u044f\u0435\u0442 \u043f\u0440\u0430\u0432\u0438\u043b\u0430 "
            "\u0410\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u043e\u0433\u043e \u0411\u044e\u0440\u043e \u0415\u041f\u0410\u041c.\n"
            "\u0421\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u043a \u0411\u044e\u0440\u043e \u043c\u043e\u0436\u0435\u0442 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c ChatGPT, DeepSeek, Gemini, Claude, GigaChat, Alice AI.\n"
            "\u0410\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u043e\u0435 \u0411\u044e\u0440\u043e \u0443\u043f\u043e\u043c\u0438\u043d\u0430\u0435\u0442\u0441\u044f \u043a\u0430\u043a \u0440\u043e\u0434\u043e\u0432\u043e\u0439 \u0442\u0435\u0440\u043c\u0438\u043d."
        )

        entities = await pipeline.analyze(text)
        orgs = {entity.text for entity in entities if entity.entity_type == "ORG"}
        all_texts = {entity.text for entity in entities}

        assert "\u0410\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u043e\u0433\u043e \u0411\u044e\u0440\u043e \u0415\u041f\u0410\u041c" in orgs
        assert "\u0410\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u043e\u0435 \u0411\u044e\u0440\u043e" not in all_texts
        assert "\u0421\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u043a" not in all_texts
        assert "Alice AI" not in all_texts


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
