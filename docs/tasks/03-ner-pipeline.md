# Task 03: NER Pipeline (Presidio + spaCy + GLiNER + LLM)

## Контекст

Task 02 создала regex-распознаватели — слой 1. Теперь нужен полный pipeline, объединяющий все три слоя в один сервис `NERPipeline`.

## Зависимости

- Task 02 (regex recognizers)
- Прочитать `docs/adr/0002-three-layer-ner-pipeline.md`
- Прочитать `docs/adr/0003-presidio-as-orchestrator.md`
- Прочитать `docs/adr/0004-ollama-for-local-llm.md`

## Цель

Создать сервис `NERPipeline`, который принимает текст и возвращает список обнаруженных сущностей со всех трёх слоёв, дедуплицированных и слитых в единый результат.

## Требования

### Структура

```python
# backend/app/services/ner_pipeline.py

from typing import Literal
from pydantic import BaseModel
from presidio_analyzer import AnalyzerEngine, RecognizerResult
from app.services.regex_recognizers import (
    InnRecognizer, OgrnRecognizer, SnilsRecognizer, ...
)
from app.services.gliner_recognizer import GLiNERRecognizer
from app.services.local_llm_verifier import LocalLLMVerifier


EntityType = Literal[
    "PER", "ORG", "LOC", "ADDR", "MON", "DATE",
    "RU_INN", "RU_OGRN", "RU_SNILS", "RU_PASSPORT",
    "RU_BANK_ACCOUNT", "PHONE", "EMAIL", "CASE_NUMBER",
    "POSITION", "PROJECT_CODENAME"
]


class DetectedEntity(BaseModel):
    text: str              # оригинальный текст сущности
    entity_type: EntityType
    start: int             # позиция в исходном тексте
    end: int
    score: float           # 0.0 - 1.0
    source_layer: Literal["regex", "ner", "llm"]
    metadata: dict = {}


class NERPipeline:
    """Three-layer NER pipeline for CLEARGATE."""

    def __init__(
        self,
        spacy_model: str = "ru_core_news_lg",
        gliner_model: str = "urchade/gliner_medium-v2.1",
        ollama_model: str = "qwen2.5:7b-instruct-q4_K_M",
        enable_llm_layer: bool = True,
    ) -> None:
        self.analyzer = self._build_presidio_analyzer(spacy_model)
        self.gliner = GLiNERRecognizer(gliner_model)
        self.llm_verifier = LocalLLMVerifier(ollama_model) if enable_llm_layer else None

    def _build_presidio_analyzer(self, spacy_model: str) -> AnalyzerEngine:
        """Build Presidio analyzer with spaCy ru and all custom recognizers."""
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "ru", "model_name": spacy_model}],
        }
        nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()

        analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=["ru", "en"],
        )

        # Register custom Russian recognizers
        for recognizer_cls in [
            InnRecognizer, OgrnRecognizer, SnilsRecognizer,
            PassportRfRecognizer, BankAccountRecognizer,
            PhoneRuRecognizer, EmailRecognizer,
            DateRuRecognizer, CaseNumberRecognizer,
        ]:
            analyzer.registry.add_recognizer(recognizer_cls())

        return analyzer

    async def analyze(
        self,
        text: str,
        language: Literal["ru", "en"] = "ru",
        custom_entities: list[str] | None = None,
    ) -> list[DetectedEntity]:
        """Run all three layers and return merged entities."""
        # Layer 1+2: Presidio (regex + spaCy NER)
        presidio_results = self.analyzer.analyze(text=text, language=language)
        entities = self._convert_presidio_results(text, presidio_results)

        # Layer 2 extra: GLiNER for custom entities
        if custom_entities:
            gliner_results = await self.gliner.detect(text, labels=custom_entities)
            entities.extend(gliner_results)

        # Layer 3: Local LLM verification (если включено)
        if self.llm_verifier:
            entities = await self.llm_verifier.verify_and_refine(text, entities)

        # Дедупликация и мерджинг
        entities = self._merge_overlapping(entities)
        entities = self._sort_and_renumber(entities)

        return entities

    def _convert_presidio_results(
        self, text: str, results: list[RecognizerResult]
    ) -> list[DetectedEntity]:
        """Convert Presidio RecognizerResult to DetectedEntity."""
        ...

    def _merge_overlapping(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Merge overlapping spans, prefer higher score and earlier source layer."""
        ...

    def _sort_and_renumber(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Sort by position in text."""
        ...
```

### GLiNER recognizer adapter

```python
# backend/app/services/gliner_recognizer.py

from gliner import GLiNER
from app.services.ner_pipeline import DetectedEntity


class GLiNERRecognizer:
    """Zero-shot custom entity recognition via GLiNER."""

    def __init__(self, model_name: str = "urchade/gliner_medium-v2.1") -> None:
        self.model = GLiNER.from_pretrained(model_name)

    async def detect(
        self,
        text: str,
        labels: list[str],
        threshold: float = 0.5,
    ) -> list[DetectedEntity]:
        """Detect custom entities by zero-shot labels."""
        results = self.model.predict_entities(text, labels, threshold=threshold)
        return [
            DetectedEntity(
                text=r["text"],
                entity_type=self._map_label_to_type(r["label"]),
                start=r["start"],
                end=r["end"],
                score=r["score"],
                source_layer="ner",
            )
            for r in results
        ]
```

### Local LLM verifier

```python
# backend/app/services/local_llm_verifier.py

import json
import ollama
from app.services.ner_pipeline import DetectedEntity


VERIFICATION_PROMPT = """Ты эксперт по обработке юридических текстов. Тебе дан текст и список кандидатов в чувствительные сущности. Твоя задача:

1. Подтвердить, что каждый кандидат — действительно чувствительная сущность
2. Найти упущенные сущности (особенно: кореференции, составные сущности, упоминания через должность)
3. Связать упоминания одной и той же сущности (например, "Иванов" и "генеральный директор")

Верни строго JSON в формате:
{{
  "verified": [
    {{"text": "...", "type": "PER|ORG|...", "start": N, "end": N, "score": 0.0-1.0, "reason": "..."}}
  ],
  "added": [...]
}}

ТЕКСТ:
{text}

КАНДИДАТЫ:
{candidates}
"""


class LocalLLMVerifier:
    def __init__(self, model: str = "qwen2.5:7b-instruct-q4_K_M") -> None:
        self.model = model
        self.client = ollama.AsyncClient()

    async def verify_and_refine(
        self,
        text: str,
        candidates: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        if not candidates:
            return candidates

        prompt = VERIFICATION_PROMPT.format(
            text=text[:8000],  # cap context for 7B model
            candidates=json.dumps([c.model_dump() for c in candidates], ensure_ascii=False),
        )

        response = await self.client.generate(
            model=self.model,
            prompt=prompt,
            format="json",
            options={"temperature": 0.0},
        )

        result = json.loads(response["response"])
        return [DetectedEntity(**e, source_layer="llm") for e in result.get("verified", [])]
```

## Файлы для создания

```
backend/app/services/ner_pipeline.py
backend/app/services/gliner_recognizer.py
backend/app/services/local_llm_verifier.py
backend/app/models/entities.py
backend/tests/services/test_ner_pipeline.py
backend/tests/services/test_gliner_recognizer.py
backend/tests/fixtures/sample_legal_texts.json
```

## Тесты

### Test fixtures
`tests/fixtures/sample_legal_texts.json` — синтетические юридические тексты с известной разметкой:
```json
[
  {
    "id": "contract_simple",
    "text": "Общество с ограниченной ответственностью «Ромашка» (ИНН 7707083893) в лице Генерального директора Иванова Ивана Ивановича заключило договор с гражданином Петровым Петром Петровичем (паспорт 4509 123456) на сумму 1 500 000 рублей.",
    "expected_entities": [
      {"text": "Ромашка", "type": "ORG"},
      {"text": "7707083893", "type": "RU_INN"},
      {"text": "Иванова Ивана Ивановича", "type": "PER"},
      {"text": "Петровым Петром Петровичем", "type": "PER"},
      {"text": "4509 123456", "type": "RU_PASSPORT"},
      {"text": "1 500 000 рублей", "type": "MON"}
    ],
    "min_recall": 0.95
  }
]
```

### Тесты pipeline
- `test_pipeline_finds_inn_in_context`
- `test_pipeline_merges_overlapping_entities`
- `test_pipeline_handles_empty_text`
- `test_pipeline_with_disabled_llm_layer` (для CI без GPU)
- `test_pipeline_metrics_on_sample_corpus` — расчёт recall/precision на fixtures

## Acceptance Criteria

- [ ] `NERPipeline` инициализируется без ошибок
- [ ] Pipeline загружает spaCy ru_core_news_lg, GLiNER, и подключается к Ollama
- [ ] На синтетическом тестовом корпусе recall ≥ 95%
- [ ] На синтетическом тестовом корпусе precision ≥ 90%
- [ ] Время обработки ≤ 12 секунд на текст из 10 страниц на Alpha
- [ ] Все три слоя могут быть отключены независимо (для тестов и degraded modes)
- [ ] mypy и ruff без ошибок
- [ ] Документация: docstring для каждого публичного метода

## Команды для запуска

```powershell
cd backend
.\.venv\Scripts\activate

# Загрузить spaCy модель (один раз)
python -m spacy download ru_core_news_lg

# Загрузить Qwen через Ollama (один раз)
ollama pull qwen2.5:7b-instruct-q4_K_M

# Тесты
pytest tests/services/test_ner_pipeline.py -v -m "not slow"

# С LLM-слоем (требует Ollama running)
ollama serve
pytest tests/services/test_ner_pipeline.py -v
```

## Коммит

```
feat(backend): implement three-layer NER pipeline

Implements NERPipeline orchestrating three layers:
- Layer 1: Presidio with custom Russian regex recognizers (Task 02)
- Layer 2: spaCy ru_core_news_lg + GLiNER for zero-shot custom entities
- Layer 3: Local Qwen 2.5 via Ollama for verification and coreference

Includes entity merging (overlap resolution by score and source layer),
synthetic test corpus with recall/precision metrics.

Achieves >95% recall and >90% precision on synthetic corpus.

Closes task #3
```
