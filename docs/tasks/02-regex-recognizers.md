# Task 02: Russian PII Regex Recognizers

## Контекст

Первый слой NER pipeline — regex-распознаватели для российских структурированных идентификаторов. Это самый быстрый и точный слой, дающий 100% precision на структурированных ID благодаря валидации контрольных сумм. Все распознаватели реализуются как кастомные `PatternRecognizer` для Microsoft Presidio.

## Зависимости

- Task 01 (project initialization)
- Прочитать `docs/adr/0002-three-layer-ner-pipeline.md`
- Прочитать `docs/adr/0003-presidio-as-orchestrator.md`

## Цель

Создать модуль `backend/app/services/regex_recognizers.py` с готовыми Presidio-распознавателями для всех ключевых российских PII, плюс полные unit-тесты.

## Требования

Реализовать следующие классы-распознаватели (каждый — наследник `PatternRecognizer`):

### 1. InnRecognizer (ИНН)
- **Физлицо**: 12 цифр, валидация двух контрольных сумм (11-я и 12-я цифры)
- **Юрлицо**: 10 цифр, валидация контрольной суммы (10-я цифра)
- Контекстные слова: `["инн", "налоговый номер"]`
- Алгоритм контрольной суммы:
  - Для 10 цифр: коэффициенты `[2, 4, 10, 3, 5, 9, 4, 6, 8]`, сумма mod 11 mod 10
  - Для 12 цифр: два коэффициент-вектора, две контрольные цифры

### 2. OgrnRecognizer (ОГРН/ОГРНИП)
- **ОГРН**: 13 цифр, контрольное число = (число из первых 12) mod 11 (если 10 → 0)
- **ОГРНИП**: 15 цифр, аналогично mod 13
- Контекстные слова: `["огрн", "огрнип", "регистрационный номер"]`

### 3. SnilsRecognizer (СНИЛС)
- Формат: `XXX-XXX-XXX XX` или `XXXXXXXXXXX` (11 цифр)
- Алгоритм контрольной суммы (только для номеров > 001-001-998):
  - Сумма произведений первых 9 цифр на коэффициенты от 9 до 1
  - Если сумма < 100 → она и есть контрольное число
  - Если сумма == 100 или 101 → контрольное число = 00
  - Если сумма > 101 → (сумма mod 101), если результат 100 или 101 → 00
- Контекстные слова: `["снилс", "пенсионное", "страховое свидетельство"]`

### 4. PassportRfRecognizer (Паспорт РФ)
- Формат: `XXXX XXXXXX` (4 цифры серия + 6 цифр номер) или слитно `XXXXXXXXXX`
- Серия — допустимые префиксы (первые 2 цифры — год выдачи 90-25, или коды регионов)
- Контекстные слова: `["паспорт", "паспорта", "удостоверение личности"]`

### 5. BankAccountRecognizer (Банковский счёт)
- Формат: 20 цифр
- Если рядом БИК — валидация контрольного ключа (опционально, MVP)
- Контекстные слова: `["счёт", "р/с", "расчётный счёт", "корреспондентский счёт", "к/с"]`

### 6. PhoneRuRecognizer (Телефон РФ)
- Форматы: `+7XXXXXXXXXX`, `8XXXXXXXXXX`, `+7 (XXX) XXX-XX-XX`, `8 (XXX) XXX-XX-XX`
- Любой пробел/дефис/скобка между группами
- Контекстные слова: `["телефон", "тел", "моб", "сот", "номер"]`

### 7. EmailRecognizer
- Стандартный RFC 5322 regex (можно использовать готовый из Presidio с overrides)
- Контекстные слова: `["email", "почта", "электронная почта", "e-mail"]`

### 8. DateRuRecognizer
- Форматы: `ДД.ММ.ГГГГ`, `ДД.ММ.ГГ`, `ДД месяц ГГГГ` (где месяц — название на русском)
- Валидация диапазона дат (1900-2099)
- Контекстные слова: `["дата", "от", "по состоянию на", "г."]`

### 9. CaseNumberRecognizer (Номер судебного дела)
- Арбитражный: `А40-12345/2026` (буква + регион + номер + год)
- СОЮ: `2-1234/2026`, `33-567/2026`
- Дисциплинарный: разные форматы, regex покрывающий основные
- Контекстные слова: `["дело", "номер дела", "арбитражное дело"]`

### 10. AccountIBANRecognizer (МСФО — опционально)
- Стандартный IBAN regex
- Контекстные слова: `["iban", "счёт"]`

## Файлы для создания

```
backend/app/services/regex_recognizers.py
backend/app/services/checksum_validators.py    # утилиты валидации
backend/tests/services/test_regex_recognizers.py
backend/tests/services/test_checksum_validators.py
backend/tests/fixtures/synthetic_pii.json      # тестовые примеры
```

## Реализация (структура)

```python
# backend/app/services/regex_recognizers.py
from presidio_analyzer import Pattern, PatternRecognizer
from typing import Optional
from app.services.checksum_validators import (
    validate_inn_10, validate_inn_12, validate_ogrn,
    validate_snils, validate_bank_account,
)


class InnRecognizer(PatternRecognizer):
    """Recognizes Russian INN (Tax ID Number) for individuals (12 digits)
    and legal entities (10 digits)."""

    PATTERNS = [
        Pattern(name="inn_12", regex=r"\b\d{12}\b", score=0.5),
        Pattern(name="inn_10", regex=r"\b\d{10}\b", score=0.5),
    ]

    CONTEXT = ["инн", "налоговый номер", "ИНН"]

    def __init__(
        self,
        patterns: Optional[list[Pattern]] = None,
        context: Optional[list[str]] = None,
        supported_language: str = "ru",
    ) -> None:
        super().__init__(
            supported_entity="RU_INN",
            patterns=patterns or self.PATTERNS,
            context=context or self.CONTEXT,
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate INN by checksum."""
        digits = pattern_text.strip()
        if len(digits) == 10:
            return validate_inn_10(digits)
        elif len(digits) == 12:
            return validate_inn_12(digits)
        return False


# ... аналогично для остальных распознавателей
```

```python
# backend/app/services/checksum_validators.py
def validate_inn_10(inn: str) -> bool:
    """Validate 10-digit INN (legal entity) by checksum."""
    if len(inn) != 10 or not inn.isdigit():
        return False
    coefficients = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum = sum(int(inn[i]) * coefficients[i] for i in range(9)) % 11 % 10
    return checksum == int(inn[9])


def validate_inn_12(inn: str) -> bool:
    """Validate 12-digit INN (individual) by two checksums."""
    if len(inn) != 12 or not inn.isdigit():
        return False
    coef1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    coef2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    check1 = sum(int(inn[i]) * coef1[i] for i in range(10)) % 11 % 10
    check2 = sum(int(inn[i]) * coef2[i] for i in range(11)) % 11 % 10
    return check1 == int(inn[10]) and check2 == int(inn[11])


def validate_ogrn(ogrn: str) -> bool:
    """Validate 13-digit OGRN."""
    if len(ogrn) != 13 or not ogrn.isdigit():
        return False
    base = int(ogrn[:12])
    checksum = base % 11 % 10
    return checksum == int(ogrn[12])


# ... аналогично для остальных
```

## Тесты

### test_checksum_validators.py
Для каждой validate-функции:
- 3+ valid примеров (синтетические, не реальные)
- 3+ invalid примеров
- Edge cases: пустая строка, слишком короткая/длинная, нецифровые символы

### test_regex_recognizers.py
Для каждого распознавателя:
- Тест: распознавание в свободном тексте с контекстом
- Тест: распознавание без контекста (низкий confidence)
- Тест: отсутствие false positives на похожих, но невалидных строках
- Тест: контекстные слова повышают confidence

```python
# Пример теста
def test_inn_recognizer_with_context():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    # Setup analyzer with Russian spaCy
    analyzer = build_test_analyzer()
    analyzer.registry.add_recognizer(InnRecognizer())

    text = "ИНН организации: 7707083893"  # synthetic valid INN
    results = analyzer.analyze(text=text, language="ru", entities=["RU_INN"])

    assert len(results) == 1
    assert results[0].score >= 0.85  # boosted by context
    assert text[results[0].start:results[0].end] == "7707083893"
```

### Synthetic test data
`tests/fixtures/synthetic_pii.json`:
```json
{
  "valid_inn_10": ["7707083893", "7728168971", "7733506660"],
  "valid_inn_12": ["500100732259", "771572873600"],
  "invalid_inn_10": ["1234567890", "0000000000"],
  "valid_ogrn": ["1027700132195", "1037700255284"],
  "valid_snils": ["112-233-445 95"],
  "valid_passport": ["4509 123456", "7706 654321"],
  "valid_phone": ["+79161234567", "8 (916) 123-45-67"],
  "valid_email": ["test@example.ru"],
  "valid_case_number": ["А40-12345/2026", "А56-67890/2025"]
}
```

## Acceptance Criteria

- [ ] Все 9 классов-распознавателей реализованы
- [ ] Все checksum validators реализованы и протестированы
- [ ] Тесты покрывают valid и invalid примеры для каждого распознавателя
- [ ] `pytest tests/services/ -v` проходит со 100% результатом
- [ ] `mypy app/services/regex_recognizers.py` без ошибок
- [ ] `ruff check app/services/regex_recognizers.py` без warnings
- [ ] Test coverage для модуля ≥ 90%
- [ ] Все распознаватели регистрируются в Presidio analyzer без ошибок
- [ ] Документация: docstring для каждого класса с примерами использования

## Команды для запуска

```powershell
cd backend
.\.venv\Scripts\activate

# Тесты
pytest tests/services/test_regex_recognizers.py -v
pytest tests/services/test_checksum_validators.py -v

# Coverage
pytest --cov=app.services.regex_recognizers --cov-report=term-missing

# Линтинг
ruff check app/services/regex_recognizers.py
mypy app/services/regex_recognizers.py
```

## Коммит

```
feat(backend): add Russian PII regex recognizers with checksum validation

- INN (10 and 12 digit) with full checksum validation
- OGRN/OGRNIP with mod 11/13 validation
- SNILS with PFR algorithm
- Russian passport (XXXX XXXXXX format)
- Bank account (20 digits)
- Russian phone numbers (multiple formats)
- Email (RFC 5322)
- Russian dates (multiple formats)
- Court case numbers (arbitration and SOJ)

All recognizers register as Presidio PatternRecognizer with Russian
context words. Full unit test coverage (90%+).

Closes task #2
```
