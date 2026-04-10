"""Presidio PatternRecognizer classes for Russian PII.

Each recognizer detects a specific type of Russian structured identifier
using regex patterns with optional checksum validation. All recognizers
include Russian context words to boost confidence when identifiers appear
near relevant keywords.

Usage:
    from presidio_analyzer import AnalyzerEngine
    from app.services.regex_recognizers import ALL_RECOGNIZERS

    analyzer = AnalyzerEngine()
    for recognizer in ALL_RECOGNIZERS:
        analyzer.registry.add_recognizer(recognizer)
"""

from __future__ import annotations

import re

from presidio_analyzer import Pattern, PatternRecognizer

from app.services.checksum_validators import (
    validate_inn_10,
    validate_inn_12,
    validate_ogrn,
    validate_ogrnip,
    validate_snils,
)


class InnRecognizer(PatternRecognizer):
    """Recognizes Russian INN (Tax ID Number).

    Supports both 10-digit (legal entity) and 12-digit (individual) formats
    with full checksum validation.

    Examples:
        - "ИНН организации: 7707083893" → RU_INN, score >= 0.85
        - "7707083893" (without context) → RU_INN, score = 0.5
    """

    PATTERNS = [
        Pattern(name="inn_12", regex=r"\b\d{12}\b", score=0.5),
        Pattern(name="inn_10", regex=r"\b\d{10}\b", score=0.5),
    ]
    CONTEXT = ["инн", "ИНН", "налоговый номер", "идентификационный номер"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_INN",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Validate INN checksum."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) == 10:
            return validate_inn_10(digits)
        if len(digits) == 12:
            return validate_inn_12(digits)
        return False


class OgrnRecognizer(PatternRecognizer):
    """Recognizes Russian OGRN (13 digits) and OGRNIP (15 digits).

    Both formats are validated with modular checksum algorithms.

    Examples:
        - "ОГРН 1027700132195" → RU_OGRN, score >= 0.85
    """

    PATTERNS = [
        Pattern(name="ogrnip_15", regex=r"\b\d{15}\b", score=0.3),
        Pattern(name="ogrn_13", regex=r"\b\d{13}\b", score=0.3),
    ]
    CONTEXT = ["огрн", "ОГРН", "огрнип", "ОГРНИП", "регистрационный номер"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_OGRN",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Validate OGRN/OGRNIP checksum."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) == 13:
            return validate_ogrn(digits)
        if len(digits) == 15:
            return validate_ogrnip(digits)
        return False


class SnilsRecognizer(PatternRecognizer):
    """Recognizes Russian SNILS (pension insurance number).

    Supports formatted (XXX-XXX-XXX XX) and plain (11 digits) formats.

    Examples:
        - "СНИЛС: 112-233-445 95" → RU_SNILS, score >= 0.85
    """

    PATTERNS = [
        Pattern(
            name="snils_formatted",
            regex=r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b",
            score=0.5,
        ),
        Pattern(name="snils_plain", regex=r"\b\d{11}\b", score=0.2),
    ]
    CONTEXT = ["снилс", "СНИЛС", "пенсионное", "страховое свидетельство"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_SNILS",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Validate SNILS checksum."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 11:
            return False
        return validate_snils(digits)


class PassportRfRecognizer(PatternRecognizer):
    """Recognizes Russian passport numbers.

    Format: XXXX XXXXXX (4 digits series + space + 6 digits number).
    Only matches when there's a space between series and number,
    to avoid false positives with 10-digit INN numbers.

    Examples:
        - "паспорт 4509 123456" → RU_PASSPORT, score >= 0.85
    """

    PATTERNS = [
        # Require at least one space/separator between series (4 digits) and number (6 digits)
        Pattern(
            name="passport_spaced",
            regex=r"\b\d{2}\s\d{2}\s\d{6}\b",
            score=0.5,
        ),
        Pattern(
            name="passport_series_space",
            regex=r"\b\d{4}\s\d{6}\b",
            score=0.5,
        ),
    ]
    CONTEXT = [
        "паспорт",
        "паспорта",
        "удостоверение личности",
        "серия",
    ]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_PASSPORT",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Validate passport format: region code 01-99."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 10:
            return False
        region = int(digits[:2])
        return 1 <= region <= 99


class BankAccountRecognizer(PatternRecognizer):
    """Recognizes Russian bank account numbers (20 digits).

    Examples:
        - "р/с 40817810099910004312" → RU_BANK_ACCOUNT, score >= 0.85
    """

    PATTERNS = [
        Pattern(name="bank_account", regex=r"\b\d{20}\b", score=0.3),
    ]
    CONTEXT = [
        "счёт",
        "счет",
        "р/с",
        "расчётный счёт",
        "расчетный счет",
        "корреспондентский счёт",
        "корреспондентский счет",
        "к/с",
        "лицевой счёт",
        "лицевой счет",
    ]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_BANK_ACCOUNT",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Validate: 20 digits, first 3 digits are valid account category."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 20:
            return False
        # Valid first 3 digits: balance account categories (301-423, 454-479, etc.)
        first3 = int(digits[:3])
        return 100 <= first3 <= 999


class PhoneRuRecognizer(PatternRecognizer):
    """Recognizes Russian phone numbers in various formats.

    Supports +7 and 8 prefixes with optional grouping.

    Examples:
        - "+7 (916) 123-45-67" → RU_PHONE
        - "8(916)1234567" → RU_PHONE
        - "+79161234567" → RU_PHONE
    """

    PATTERNS = [
        Pattern(
            name="phone_plus7",
            regex=r"(?<!\d)\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)",
            score=0.7,
        ),
        Pattern(
            name="phone_8",
            regex=r"(?<!\d)8[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)",
            score=0.5,
        ),
    ]
    CONTEXT = ["телефон", "тел", "моб", "сот", "номер", "звонить", "позвонить"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_PHONE",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )


class EmailRuRecognizer(PatternRecognizer):
    """Recognizes email addresses.

    Uses a standard RFC 5322 simplified pattern.

    Examples:
        - "почта: user@example.ru" → EMAIL_ADDRESS
    """

    PATTERNS = [
        Pattern(
            name="email",
            regex=r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
            score=0.7,
        ),
    ]
    CONTEXT = ["email", "почта", "электронная почта", "e-mail", "емейл", "имейл"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="EMAIL_ADDRESS",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )


class DateRuRecognizer(PatternRecognizer):
    """Recognizes Russian date formats.

    Supports DD.MM.YYYY, DD.MM.YY, and "DD month YYYY" (Russian month names).

    Examples:
        - "от 15.03.2026" → RU_DATE
        - "25 января 2026 г." → RU_DATE
    """

    _MONTHS = (
        "январ[яьие]|феврал[яьие]|март[аеу]?|апрел[яьие]|ма[яйю]|"
        "июн[яьие]|июл[яьие]|август[аеу]?|сентябр[яьие]|"
        "октябр[яьие]|ноябр[яьие]|декабр[яьие]"
    )

    PATTERNS = [
        Pattern(
            name="date_dot",
            regex=r"\b(?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2])\.(?:19|20)\d{2}\b",
            score=0.6,
        ),
        Pattern(
            name="date_dot_short",
            regex=r"\b(?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2])\.\d{2}\b",
            score=0.4,
        ),
        Pattern(
            name="date_written",
            regex=rf"\b(?:0?[1-9]|[12]\d|3[01])\s+(?:{_MONTHS})\s+(?:19|20)\d{{2}}\b",
            score=0.7,
        ),
    ]
    CONTEXT = ["дата", "от", "по состоянию на", "г.", "года", "году", "число"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_DATE",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )


class CaseNumberRecognizer(PatternRecognizer):
    """Recognizes Russian court case numbers.

    Supports arbitration (А40-12345/2026) and general jurisdiction (2-1234/2026) formats.

    Examples:
        - "дело А40-12345/2026" → RU_CASE_NUMBER
        - "дело № 2-1234/2026" → RU_CASE_NUMBER
    """

    PATTERNS = [
        Pattern(
            name="arbitration",
            regex=r"\b[АA]\d{1,3}-\d{1,10}/\d{4}\b",
            score=0.85,
        ),
        Pattern(
            name="general_jurisdiction",
            regex=r"\b\d{1,2}-\d{1,10}/\d{4}\b",
            score=0.5,
        ),
    ]
    CONTEXT = ["дело", "номер дела", "арбитражное дело", "производство", "№"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_CASE_NUMBER",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )


class ContractNumberRecognizer(PatternRecognizer):
    """Recognizes contract/agreement numbers in Russian legal documents.

    Patterns: "N TL-2026/047", "N 12-A/2026", "N 2026-001", etc.
    Requires a context word (договор, контракт, соглашение, N) within proximity.

    Examples:
        - "Договор N ТЛ-2026/047" → RU_CONTRACT_NUMBER
        - "контракт N 12-СМ/25" → RU_CONTRACT_NUMBER
    """

    PATTERNS = [
        # Letter prefix + digits + separator + digits: ТЛ-2026/047, 12-А/2026
        Pattern(
            name="contract_alpha_num",
            regex=r"(?:№\s?|N\s?)[A-Za-zА-Яа-яЁё]{1,5}[\-/]\d{2,6}(?:[\-/]\d{1,5})?",
            score=0.7,
        ),
        # Pure numeric with separators: 2026-001, 15/2026
        Pattern(
            name="contract_numeric",
            regex=r"(?:№\s?|N\s?)\d{1,6}[\-/]\d{1,6}(?:[\-/]\d{1,5})?",
            score=0.5,
        ),
    ]
    CONTEXT = [
        "договор", "договора", "контракт", "контракта",
        "соглашение", "соглашения", "дог.", "дополнительное соглашение",
    ]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_CONTRACT_NUMBER",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )


def build_all_recognizers() -> list[PatternRecognizer]:
    """Create instances of all Russian PII recognizers.

    Returns:
        List of initialized PatternRecognizer instances ready for Presidio.
    """
    return [
        InnRecognizer(),
        OgrnRecognizer(),
        SnilsRecognizer(),
        PassportRfRecognizer(),
        BankAccountRecognizer(),
        PhoneRuRecognizer(),
        EmailRuRecognizer(),
        DateRuRecognizer(),
        CaseNumberRecognizer(),
        ContractNumberRecognizer(),
    ]


ALL_RECOGNIZERS = build_all_recognizers()
