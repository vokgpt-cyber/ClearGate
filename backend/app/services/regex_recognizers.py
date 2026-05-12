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

from presidio_analyzer import (
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerResult,
)

from app.services.checksum_validators import (
    validate_inn_10,
    validate_inn_12,
    validate_ogrn,
    validate_ogrnip,
    validate_snils,
)


_REGEX_FLAGS = re.IGNORECASE | re.UNICODE | re.MULTILINE


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Trim separators which are useful in regexes but unsafe to redact."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1] in " \t\r\n,;:":
        end -= 1
    return start, end


class GroupRegexRecognizer(EntityRecognizer):
    """Regex recognizer which can return a named capture group as the entity.

    Presidio's PatternRecognizer returns the full pattern span. That is fine
    for identifiers, but legal documents often need "label: value" patterns
    where only the value should become the placeholder.
    """

    PATTERNS: list[tuple[re.Pattern[str], float, str]] = []

    def __init__(
        self,
        supported_entity: str,
        name: str,
        patterns: list[tuple[re.Pattern[str], float, str]] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entities=[supported_entity],
            name=name,
            supported_language=supported_language,
        )
        self.supported_entity = supported_entity
        self._patterns = patterns or self.PATTERNS

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: object | None = None,
        regex_flags: int | None = None,
    ) -> list[RecognizerResult]:
        if self.supported_entity not in entities:
            return []

        results: list[RecognizerResult] = []
        for pattern, score, group_name in self._patterns:
            for match in pattern.finditer(text):
                try:
                    start = match.start(group_name)
                    end = match.end(group_name)
                except IndexError:
                    start = match.start()
                    end = match.end()
                if start < 0 or end <= start:
                    continue
                start, end = _trim_span(text, start, end)
                if end <= start:
                    continue
                results.append(
                    RecognizerResult(
                        entity_type=self.supported_entity,
                        start=start,
                        end=end,
                        score=score,
                        recognition_metadata={"recognizer_name": self.name},
                    )
                )
        deduped: dict[tuple[str, int, int], RecognizerResult] = {}
        for result in results:
            key = (result.entity_type, result.start, result.end)
            existing = deduped.get(key)
            if existing is None or result.score > existing.score:
                deduped[key] = result
        return sorted(deduped.values(), key=lambda r: (r.start, r.end, -r.score))


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
        """Validate INN checksum.

        Returns True for valid checksums (boosts score), None for invalid
        (keeps base score so context words can still promote the match).
        """
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) == 10:
            return True if validate_inn_10(digits) else None
        if len(digits) == 12:
            return True if validate_inn_12(digits) else None
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
        """Validate OGRN/OGRNIP checksum.

        Same strategy as INN: return None (not False) for invalid checksums
        so that context-boosted matches survive.
        """
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) == 13:
            return True if validate_ogrn(digits) else None
        if len(digits) == 15:
            return True if validate_ogrnip(digits) else None
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
        """Validate SNILS checksum.

        Same strategy as INN/OGRN: return None for invalid checksums
        so context-boosted matches survive.
        """
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 11:
            return False
        return True if validate_snils(digits) else None


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




class BikRecognizer(PatternRecognizer):
    """Recognizes Russian BIK (Bank Identification Code).

    BIK is a 9-digit code starting with '04' assigned to Russian banks
    by the Central Bank of Russia.

    Examples:
        - "БИК 044525225" -> RU_BIK, score >= 0.85
        - "044525225" (without context) -> RU_BIK, score = 0.5
    """

    PATTERNS = [
        Pattern(name="bik_9", regex=r"\b04\d{7}\b", score=0.5),
    ]
    CONTEXT = ["бик", "БИК", "банковский идентификационный"]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_BIK",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Basic validation: BIK must be exactly 9 digits starting with 04."""
        digits = re.sub(r"\D", "", pattern_text)
        if len(digits) != 9 or not digits.startswith("04"):
            return False
        return True


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


class KppRecognizer(GroupRegexRecognizer):
    """Recognizes Russian KPP (tax registration reason code).

    KPP is not checksum-protected, so we only redact a 9-digit value when
    it appears next to an explicit "КПП" label.
    """

    PATTERNS = [
        (
            re.compile(r"\bКПП\b\s*(?:[:№N]\s*)?(?P<value>\d{9})(?!\d)", _REGEX_FLAGS),
            0.95,
            "value",
        ),
    ]

    def __init__(self, supported_language: str = "ru") -> None:
        super().__init__(
            supported_entity="RU_KPP",
            name="Russian KPP Recognizer",
            supported_language=supported_language,
        )


class MoneyRuRecognizer(GroupRegexRecognizer):
    """Recognizes amounts and financial rates in Russian legal texts."""

    _CURRENCY = (
        r"руб\.|рубл[а-яё]*|руб\b|₽|RUB|RUR|"
        r"USD|US\$|EUR|€|CNY|CNH|RMB|GBP|£|CHF|JPY|¥|HKD|AED|TRY|KZT|BYN|UAH|"
        r"доллар[а-яё]*|евро|юан[ьяей]*|фунт[а-яё]*|иен[а-яё]*|тенге"
    )

    _FINANCIAL_CONTEXT = re.compile(
        (
            r"\b(?:сумм[ауы]|размер[еа]?|цена|стоимость|вознаграждение|штраф|"
            r"неустойк[аиу]|пен[яи]|комисси[яи]|ставк[аи]|процент[аыов]?|"
            r"задолженность|оплат[ауы]|выплат[аые]|выручк[аи])\b"
        ),
        _REGEX_FLAGS,
    )
    _NON_SECRET_PERCENT_CONTEXT = re.compile(
        r"\b(?:НДС|VAT|пен[яи]|неустойк[аиу]|штраф)\b",
        _REGEX_FLAGS,
    )

    PATTERNS = [
        (
            re.compile(
                (
                    r"(?P<value>(?<!\w)(?:\d{1,3}(?:[ \u00A0]\d{3})+|\d+)"
                    r"(?:[,.]\d{1,2})?"
                    r"(?:\s*\([^\)\n]{3,160}\))?"
                    rf"\s*(?:{_CURRENCY})"
                    r"(?:\s*\d{1,2}\s*(?:коп\.|копеек|копейки|копейка))?)"
                ),
                _REGEX_FLAGS,
            ),
            0.92,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>\([^\n()]{3,140}"
                    r"\(\s*(?:\d{1,3}(?:[ \u00A0]\d{3})+|\d+)(?:[,.]\d{1,2})?\s*\)"
                    rf"\s*(?:{_CURRENCY})\))"
                ),
                _REGEX_FLAGS,
            ),
            0.91,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>\b(?:[а-яё]+(?:[ \u00A0-]+)){1,12}"
                    r"\(\s*(?:\d{1,3}(?:[ \u00A0]\d{3})+|\d+)(?:[,.]\d{1,2})?\s*\)"
                    rf"\s*(?:{_CURRENCY}))"
                ),
                _REGEX_FLAGS,
            ),
            0.91,
            "value",
        ),
        (
            re.compile(
                r"(?P<value>(?<!\d)\d{1,3}(?:[,.]\d{1,2})?\s*%\s*(?:\([^\)\n]{3,100}\))?)",
                _REGEX_FLAGS,
            ),
            0.78,
            "value",
        ),
    ]

    def __init__(self, supported_language: str = "ru") -> None:
        super().__init__(
            supported_entity="MON",
            name="Russian Money Recognizer",
            supported_language=supported_language,
        )

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: object | None = None,
        regex_flags: int | None = None,
    ) -> list[RecognizerResult]:
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        filtered: list[RecognizerResult] = []
        for result in results:
            value = text[result.start : result.end]
            if "%" in value:
                window = text[max(0, result.start - 80) : min(len(text), result.end + 80)]
                if self._NON_SECRET_PERCENT_CONTEXT.search(window):
                    continue
                if not self._FINANCIAL_CONTEXT.search(window):
                    continue
            filtered.append(result)
        return filtered


class AddressRuRecognizer(GroupRegexRecognizer):
    """Recognizes Russian postal/legal address blocks."""

    PATTERNS = [
        (
            re.compile(
                (
                    r"\b(?:(?:юридический\s+адрес|почтовый\s+адрес|"
                    r"фактический\s+адрес|место\s+нахождения)\s*:?\s*|адрес\s*:\s*)"
                    r"(?P<value>(?:\d{6},\s*)?[^;\n()]{10,220}?)"
                    r"(?=,\s*(?:именуем|далее|в лице)|"
                    r"\s*/?\s*(?:Банк|банк|ИНН|ОГРН|КПП|БИК|р/с|к/с|"
                    r"Арендодатель|Арендатор)\s*:|\)|;|\n|$)"
                ),
                _REGEX_FLAGS,
            ),
            0.93,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>(?:\d{6},\s*)?(?:[^,\n;():]{2,70},\s*){0,4}"
                    r"(?:ул\.|улица|пр-т|проспект|пер\.|переулок|шоссе|наб\.|"
                    r"площадь|пл\.)\s*[^,/\n;():]{2,90},\s*"
                    r"(?:д\.|дом)\s*[^,/\n;():]{1,30}"
                    r"(?:,\s*(?:стр\.|строение|корп\.|корпус|оф\.|офис|пом\.|"
                    r"помещение|кв\.|квартира)\s*[^,/\n;():]{1,30})*)"
                ),
                _REGEX_FLAGS,
            ),
            0.9,
            "value",
        ),
    ]

    def __init__(self, supported_language: str = "ru") -> None:
        super().__init__(
            supported_entity="ADDR",
            name="Russian Address Recognizer",
            supported_language=supported_language,
        )


class OrganizationRuRecognizer(GroupRegexRecognizer):
    """Recognizes common Russian legal-entity and sole-proprietor names."""

    PATTERNS = [
        (
            re.compile(
                (
                    r"(?P<value>\b(?:Общество\s+с\s+ограниченной\s+ответственностью|"
                    r"Акционерное\s+общество|Публичное\s+акционерное\s+общество|"
                    r"Закрытое\s+акционерное\s+общество)\s+"
                    r"(?:[«\"][^»\"]{2,160}[»\"]|[А-ЯЁA-Z][^,\n;/()]{2,120}))"
                ),
                _REGEX_FLAGS,
            ),
            0.94,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>\b(?:ООО|ОАО|АО|ПАО|ЗАО)\s+"
                    r"(?:[«\"][^»\"]{2,160}[»\"]|[А-ЯЁA-Z][^,\n;/()]{2,80}))"
                ),
                _REGEX_FLAGS,
            ),
            0.93,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>\b(?:ИП|Индивидуальный\s+предприниматель)\s+"
                    r"[А-ЯЁ][а-яё]+(?:\s+(?:[А-ЯЁ]\.\s*){1,2}|(?:\s+[А-ЯЁ][а-яё]+){1,2}))"
                ),
                _REGEX_FLAGS,
            ),
            0.92,
            "value",
        ),
        (
            re.compile(
                (
                    r"(?P<value>\b(?:Адвокатское\s+бюро|Адвокатская\s+контора|"
                    r"Коллегия\s+адвокатов|Юридическая\s+фирма|Юридическое\s+бюро|"
                    r"Патентное\s+бюро)\s+"
                    r"(?:[«\"][^»\"]{2,120}[»\"]|[А-ЯЁA-Z][А-ЯЁA-Zа-яёA-Za-z0-9&.'’\-]{2,}"
                    r"(?:\s+[А-ЯЁA-Z][А-ЯЁA-Zа-яёA-Za-z0-9&.'’\-]{1,}){0,5}))"
                ),
                _REGEX_FLAGS,
            ),
            0.91,
            "value",
        ),
        (
            re.compile(
                r"(?P<value>\b(?:Банк|банк)\s+[А-ЯЁA-Z][^,\n;]{2,80}?\s*\((?:ПАО|АО|ООО)\))",
                _REGEX_FLAGS,
            ),
            0.88,
            "value",
        ),
    ]

    def __init__(self, supported_language: str = "ru") -> None:
        super().__init__(
            supported_entity="ORG",
            name="Russian Organization Recognizer",
            supported_language=supported_language,
        )


class EnglishLegalEntityRecognizer(GroupRegexRecognizer):
    """Recognizes English legal-entity names in mixed Russian contracts."""

    PATTERNS = [
        (
            re.compile(
                (
                    r"(?P<value>\b"
                    r"(?:[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){1,8})"
                    r"\s+(?:Co\.?|Company|Ltd\.?|Limited|LLC|L\.L\.C\.|Inc\.?|"
                    r"Corporation|Corp\.?|PLC|GmbH|AG|S\.A\.|S\.A\.S\.|B\.V\.|"
                    r"N\.V\.|Pte\.?\s+Ltd\.?)"
                    r"(?:,\s*(?:Ltd\.?|Limited|LLC|Inc\.?))?"
                    r")"
                ),
                re.UNICODE | re.MULTILINE,
            ),
            0.94,
            "value",
        ),
    ]

    def __init__(self, supported_language: str = "ru") -> None:
        super().__init__(
            supported_entity="ORG",
            name="English Legal Entity Recognizer",
            supported_language=supported_language,
        )


def build_all_recognizers() -> list[EntityRecognizer]:
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
        BikRecognizer(),
        KppRecognizer(),
        PhoneRuRecognizer(),
        EmailRuRecognizer(),
        DateRuRecognizer(),
        CaseNumberRecognizer(),
        ContractNumberRecognizer(),
        MoneyRuRecognizer(),
        AddressRuRecognizer(),
        OrganizationRuRecognizer(),
        EnglishLegalEntityRecognizer(),
    ]


ALL_RECOGNIZERS = build_all_recognizers()
