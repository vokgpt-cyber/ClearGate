# ADR-0003: Microsoft Presidio as anonymization orchestrator

**Дата:** 2026-04-09
**Статус:** Accepted
**Авторы:** EPAM Legal Dev

## Контекст

После принятия трёхслойного pipeline (см. [ADR-0002](0002-three-layer-ner-pipeline.md)) нужен фреймворк, который позволяет:
- Регистрировать кастомные распознаватели (regex и NER)
- Запускать их единым API
- Получать результаты с типами сущностей, позициями, confidence scores
- Применять обезличивание (замену) с настраиваемыми операторами

Альтернативы:
1. **Microsoft Presidio** — open-source PII detection framework
2. Написать оркестратор с нуля
3. Использовать spaCy напрямую без оркестратора

## Решение

Использовать **Microsoft Presidio v2.2+** как оркестратор для всех NER-слоёв (regex и spaCy/GLiNER). Слой LLM (Qwen 2.5) реализуется отдельно и интегрируется на уровне `NERPipeline` сервиса.

## Альтернативы, которые рассматривались

### Свой оркестратор с нуля
- ✅ Полный контроль
- ❌ Изобретение велосипеда
- ❌ Нужно реализовать: deduplication, merging overlapping spans, confidence aggregation, anonymization operators
- ❌ Solo-разработчик потратит недели на то, что Presidio уже делает

### spaCy напрямую
- ✅ Простота
- ❌ spaCy — это NER engine, не PII detection framework
- ❌ Нужно вручную писать regex-распознаватели и логику замены
- ❌ Нет понятия confidence score / context words / pattern recognizers

### scrubadub (Python PII library)
- ✅ Простой API
- ❌ Слабая поддержка русского языка (нет out of the box)
- ❌ Меньшая экосистема, реже обновления
- ❌ Не поддерживает spaCy как NLP engine из коробки

## Решение в деталях

Конфигурация Presidio для CLEARGATE:

1. **NLP Engine**: spaCy с моделью `ru_core_news_lg`
2. **Recognizers** (зарегистрированы при старте):
   - Custom `PatternRecognizer` для российских ID (ИНН, ОГРН, СНИЛС, паспорт, банк счёт, телефон, email, дата, номер дела)
   - Default spaCy recognizer (PERSON, LOCATION, ORGANIZATION)
   - GLiNER recognizer через адаптер
3. **Anonymization operators**:
   - Custom оператор `consistent_replace` который использует EntityRegistry для маппинга

## Почему именно Presidio

- ✅ Open-source, MIT лицензия
- ✅ Активная разработка, поддержка от Microsoft
- ✅ Архитектура built-for-extension: легко добавить custom recognizers
- ✅ Из коробки знает про context words (повышение confidence при наличии подсказки)
- ✅ Готовые операторы анонимизации (replace, hash, mask, redact, encrypt)
- ✅ Интеграция со spaCy, transformers, GLiNER через примеры в репозитории
- ✅ Production-ready: используется в Microsoft и сторонних компаниях

## Последствия

### Положительные
- Не нужно изобретать оркестратор
- Получаем confidence scores и context boosting бесплатно
- Стандартизированный API: `analyzer.analyze(text=..., language="ru", entities=[...])`
- Можно опубликовать наши русские recognizers как community contribution в будущем

### Отрицательные / компромиссы
- Из коробки **не поддерживает русский язык** → нужно вручную настраивать NLP engine со spaCy ru
- API ориентирован на английский → некоторые подсказки и примеры не применимы
- LLM-слой не вписывается в Presidio model — нужен отдельный оркестратор поверх

### Нейтральные
- Зависимость от Microsoft проекта (но MIT лицензия + active maintenance компенсируют)

## Конфигурация (псевдокод)

```python
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

# spaCy ru как NLP engine
configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "ru", "model_name": "ru_core_news_lg"}],
}
nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()

# Analyzer с русским
analyzer = AnalyzerEngine(
    nlp_engine=nlp_engine,
    supported_languages=["ru", "en"],
)

# Регистрируем кастомные recognizers
from app.services.regex_recognizers import (
    InnRecognizer, OgrnRecognizer, SnilsRecognizer,
    PassportRecognizer, BankAccountRecognizer, PhoneRecognizer,
    EmailRecognizer, DateRecognizer, CaseNumberRecognizer,
)

for r in [InnRecognizer(), OgrnRecognizer(), SnilsRecognizer(), ...]:
    analyzer.registry.add_recognizer(r)

# Анализ
results = analyzer.analyze(text=text, language="ru")
```

## Связанные ADR

- [ADR-0002](0002-three-layer-ner-pipeline.md) — общий pipeline
- [ADR-0005](0005-entity-registry-design.md) — как Presidio interacts с EntityRegistry

## Ссылки

- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [Adding recognizers to Presidio](https://microsoft.github.io/presidio/analyzer/adding_recognizers/)
- [Presidio with non-English languages](https://microsoft.github.io/presidio/tutorial/05_languages/)
