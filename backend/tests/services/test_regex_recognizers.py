"""Tests for Russian PII regex recognizers.

Tests verify that each recognizer correctly detects its entity type,
validates checksums, and handles context words. We test recognizers
directly (not through AnalyzerEngine) for speed and isolation.
"""

import json
from pathlib import Path

import pytest
from presidio_analyzer import RecognizerResult

from app.services.regex_recognizers import (
    AddressRuRecognizer,
    BankAccountRecognizer,
    BikRecognizer,
    CaseNumberRecognizer,
    DateRuRecognizer,
    EmailRuRecognizer,
    EnglishLegalEntityRecognizer,
    InnRecognizer,
    KppRecognizer,
    MoneyRuRecognizer,
    OgrnRecognizer,
    OrganizationRuRecognizer,
    PassportRfRecognizer,
    PhoneRuRecognizer,
    SnilsRecognizer,
    build_all_recognizers,
)

FIXTURES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "synthetic_pii.json").read_text()
)


def _analyze(recognizer, text):
    """Run a recognizer directly on text and return results."""
    return recognizer.analyze(text=text, entities=[recognizer.supported_entities[0]])


class TestInnRecognizer:
    @pytest.fixture()
    def rec(self):
        return InnRecognizer()

    def test_valid_inn_10_detected(self, rec):
        results = _analyze(rec, "ИНН организации: 7707083893")
        assert len(results) >= 1
        assert any(r.score > 0 for r in results)

    def test_valid_inn_12_detected(self, rec):
        results = _analyze(rec, "ИНН физлица 500100732259")
        assert len(results) >= 1

    def test_validate_result_inn_10(self, rec):
        assert rec.validate_result("7707083893") is True
        assert rec.validate_result("7728168971") is True
        assert rec.validate_result("5024002119") is True

    def test_validate_result_inn_10_invalid(self, rec):
        assert rec.validate_result("1234567890") is None
        assert rec.validate_result("7707083894") is None

    def test_validate_result_inn_12(self, rec):
        assert rec.validate_result("500100732259") is True

    def test_validate_result_inn_12_invalid(self, rec):
        assert rec.validate_result("123456789012") is None

    def test_validate_result_bad_input(self, rec):
        assert rec.validate_result("abc") is False
        assert rec.validate_result("") is False
        assert rec.validate_result("12345") is False


class TestOgrnRecognizer:
    @pytest.fixture()
    def rec(self):
        return OgrnRecognizer()

    def test_valid_ogrn_detected(self, rec):
        results = _analyze(rec, "ОГРН компании 1027700132195")
        assert len(results) >= 1

    def test_validate_result_ogrn(self, rec):
        assert rec.validate_result("1027700132195") is True
        assert rec.validate_result("1037739169335") is True

    def test_validate_result_ogrn_invalid(self, rec):
        assert rec.validate_result("1234567890123") is None

    def test_validate_result_ogrnip(self, rec):
        assert rec.validate_result("304500116000157") is True

    def test_validate_result_ogrnip_invalid(self, rec):
        assert rec.validate_result("123456789012345") is None

    def test_validate_result_bad_input(self, rec):
        assert rec.validate_result("abc") is False


class TestSnilsRecognizer:
    @pytest.fixture()
    def rec(self):
        return SnilsRecognizer()

    def test_formatted_detected(self, rec):
        results = _analyze(rec, "СНИЛС: 112-233-445 95")
        assert len(results) >= 1

    def test_validate_result_valid(self, rec):
        assert rec.validate_result("112-233-445 95") is True
        assert rec.validate_result("11223344595") is True

    def test_validate_result_invalid(self, rec):
        assert rec.validate_result("11223344500") is None

    def test_validate_result_bad_input(self, rec):
        assert rec.validate_result("abc") is False
        assert rec.validate_result("123") is False


class TestPassportRfRecognizer:
    @pytest.fixture()
    def rec(self):
        return PassportRfRecognizer()

    def test_detected_in_text(self, rec):
        results = _analyze(rec, "паспорт серия 4509 123456")
        assert len(results) >= 1

    def test_validate_result_valid(self, rec):
        assert rec.validate_result("4509 123456") is True
        assert rec.validate_result("4509123456") is True
        assert rec.validate_result("7706 654321") is True

    def test_validate_result_invalid_region(self, rec):
        assert rec.validate_result("0009 123456") is False

    def test_validate_result_bad_length(self, rec):
        assert rec.validate_result("12345") is False


class TestBankAccountRecognizer:
    @pytest.fixture()
    def rec(self):
        return BankAccountRecognizer()

    def test_detected_with_context(self, rec):
        results = _analyze(rec, "расчётный счёт 40817810099910004312")
        assert len(results) >= 1

    def test_validate_result_valid(self, rec):
        assert rec.validate_result("40817810099910004312") is True
        assert rec.validate_result("30101810400000000225") is True

    def test_validate_result_bad_length(self, rec):
        assert rec.validate_result("12345") is False


class TestBikRecognizer:
    @pytest.fixture()
    def rec(self):
        return BikRecognizer()

    def test_detected_with_context(self, rec):
        results = _analyze(rec, "БИК 044525225")
        assert len(results) >= 1


class TestKppRecognizer:
    @pytest.fixture()
    def rec(self):
        return KppRecognizer()

    def test_detects_value_after_label(self, rec):
        results = _analyze(rec, "ИНН 7707083893, КПП 770701001")
        assert len(results) == 1
        assert results[0].entity_type == "RU_KPP"
        assert results[0].start == 20
        assert results[0].end == 29

    def test_unlabeled_9_digits_not_detected(self, rec):
        results = _analyze(rec, "044525225")
        assert len(results) == 0


class TestMoneyRuRecognizer:
    @pytest.fixture()
    def rec(self):
        return MoneyRuRecognizer()

    def test_detects_currency_amount(self, rec):
        results = _analyze(rec, "штраф 1 000 000 (один миллион) рублей")
        assert len(results) == 1

    def test_detects_rub_currency_code_amount(self, rec):
        text = "Цена договора составляет 200 000 000 (Двести миллионов) RUB, включая НДС 20%."
        results = _analyze(rec, text)
        matched = [text[r.start : r.end] for r in results]
        assert any("200 000 000" in value and "RUB" in value for value in matched)

    def test_detects_cny_currency_code_amount_with_english_words(self, rec):
        text = (
            "Цена договора составляет 4 500 000 "
            "(Four million five hundred thousand) CNY, включая НДС 20%."
        )
        results = _analyze(rec, text)
        matched = [text[r.start : r.end] for r in results]
        assert any("4 500 000" in value and "CNY" in value for value in matched)

    def test_detects_financial_percent_with_context(self, rec):
        results = _analyze(rec, "вознаграждение составляет 5% (пять процентов)")
        assert len(results) == 1

    def test_ignores_percent_without_financial_context(self, rec):
        results = _analyze(rec, "готовность системы 99%")
        assert len(results) == 0


class TestAddressRuRecognizer:
    @pytest.fixture()
    def rec(self):
        return AddressRuRecognizer()

    def test_detects_labeled_address_value(self, rec):
        text = "адрес: 101000, г. Москва, ул. Мясницкая, д. 24, стр. 1, оф. 305), далее"
        results = _analyze(rec, text)
        assert len(results) == 1
        assert text[results[0].start : results[0].end] == (
            "101000, г. Москва, ул. Мясницкая, д. 24, стр. 1, оф. 305"
        )

    def test_does_not_treat_email_address_label_as_postal_address(self, rec):
        results = _analyze(rec, "адрес электронной почты: user@example.ru")
        assert len(results) == 0


class TestOrganizationRuRecognizer:
    @pytest.fixture()
    def rec(self):
        return OrganizationRuRecognizer()

    def test_detects_legal_form_with_quotes(self, rec):
        results = _analyze(rec, "АО «Норд-Хим» / ИП Кравцов А.В.")
        texts = {"АО «Норд-Хим»", "ИП Кравцов А.В."}
        assert {("АО «Норд-Хим» / ИП Кравцов А.В.")[r.start : r.end] for r in results} == texts


class TestEnglishLegalEntityRecognizer:
    @pytest.fixture()
    def rec(self):
        return EnglishLegalEntityRecognizer()

    def test_detects_english_company_with_co_suffix(self, rec):
        text = "МЕЖДУ: АО «Норд-Хим» / Tianjin Forward Polymers Co."
        results = _analyze(rec, text)
        matched = {text[r.start : r.end] for r in results}
        assert "Tianjin Forward Polymers Co." in matched

    def test_detects_company_limited_suffix(self, rec):
        text = "Покупатель: Global Trade Solutions Limited"
        results = _analyze(rec, text)
        matched = {text[r.start : r.end] for r in results}
        assert "Global Trade Solutions Limited" in matched


class TestPhoneRuRecognizer:
    @pytest.fixture()
    def rec(self):
        return PhoneRuRecognizer()

    def test_plus7_format(self, rec):
        results = _analyze(rec, "телефон +7 (916) 123-45-67")
        assert len(results) >= 1

    def test_8_format(self, rec):
        results = _analyze(rec, "тел. 8(916)1234567")
        assert len(results) >= 1

    def test_compact_format(self, rec):
        results = _analyze(rec, "моб. +79161234567")
        assert len(results) >= 1


class TestEmailRecognizer:
    @pytest.fixture()
    def rec(self):
        return EmailRuRecognizer()

    def test_with_context(self, rec):
        results = _analyze(rec, "электронная почта: user@example.ru")
        assert len(results) >= 1

    def test_without_context(self, rec):
        results = _analyze(rec, "user@example.ru")
        assert len(results) >= 1

    def test_invalid_not_detected(self, rec):
        results = _analyze(rec, "plaintext without at sign")
        assert len(results) == 0


class TestDateRuRecognizer:
    @pytest.fixture()
    def rec(self):
        return DateRuRecognizer()

    def test_dot_format(self, rec):
        results = _analyze(rec, "дата 15.03.2026")
        assert len(results) >= 1

    def test_written_format(self, rec):
        results = _analyze(rec, "25 января 2026 года")
        assert len(results) >= 1

    def test_short_year(self, rec):
        results = _analyze(rec, "от 01.01.26")
        assert len(results) >= 1


class TestCaseNumberRecognizer:
    @pytest.fixture()
    def rec(self):
        return CaseNumberRecognizer()

    def test_arbitration(self, rec):
        results = _analyze(rec, "дело А40-12345/2026")
        assert len(results) >= 1

    def test_general_jurisdiction(self, rec):
        results = _analyze(rec, "дело № 2-1234/2026")
        assert len(results) >= 1


class TestBuildAllRecognizers:
    def test_returns_15_recognizers(self):
        recognizers = build_all_recognizers()
        assert len(recognizers) == 15

    def test_all_have_supported_language_ru(self):
        for r in build_all_recognizers():
            assert r.supported_language == "ru"

    def test_all_have_entity_type(self):
        entity_types = {r.supported_entities[0] for r in build_all_recognizers()}
        expected = {
            "RU_INN",
            "RU_OGRN",
            "RU_SNILS",
            "RU_PASSPORT",
            "RU_BANK_ACCOUNT",
            "RU_BIK",
            "RU_KPP",
            "RU_PHONE",
            "EMAIL_ADDRESS",
            "RU_DATE",
            "RU_CASE_NUMBER",
            "RU_CONTRACT_NUMBER",
            "MON",
            "ADDR",
            "ORG",
        }
        assert entity_types == expected

    def test_module_level_all_recognizers(self):
        from app.services.regex_recognizers import ALL_RECOGNIZERS

        assert len(ALL_RECOGNIZERS) == 15
