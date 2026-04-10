# CLAUDE.md — Backend (Python/FastAPI)

Sub-инструкции для Claude Code при работе в каталоге `backend/`. Этот файл дополняет root [`CLAUDE.md`](../CLAUDE.md), не заменяет его.

## Обзор

Backend VELUM — Python 3.12 + FastAPI 0.116. Содержит трёхслойный NER pipeline (Presidio + spaCy + GLiNER + Ollama Qwen 2.5), EntityRegistry с AES-256-GCM шифрованием, нативные адаптеры для Claude/OpenAI/Gemini API, и REST + WebSocket endpoints.

## Структура

```
backend/
├── app/
│   ├── main.py                   # FastAPI app, lifespan, middleware
│   ├── config.py                 # Pydantic Settings, профили alpha/mvp/final
│   ├── routers/                  # FastAPI endpoints
│   │   ├── health.py
│   │   ├── sessions.py
│   │   ├── documents.py
│   │   ├── anonymize.py
│   │   └── llm_ws.py            # WebSocket streaming
│   ├── services/                 # Бизнес-логика
│   │   ├── ner_pipeline.py      # Оркестрация трёх слоёв
│   │   ├── regex_recognizers.py # Российские PII regex
│   │   ├── checksum_validators.py
│   │   ├── gliner_recognizer.py
│   │   ├── local_llm_verifier.py
│   │   ├── entity_registry.py   # Маппинг с шифрованием
│   │   ├── entity_normalizer.py # pymorphy3 + Natasha
│   │   ├── crypto.py            # AES-256-GCM
│   │   ├── doc_processor.py     # DOCX/PDF/TXT парсинг
│   │   ├── chunker.py           # Чанкинг больших документов
│   │   ├── session_manager.py   # In-memory session storage
│   │   └── llm_adapters/        # Нативные адаптеры
│   │       ├── base.py
│   │       ├── claude.py
│   │       ├── openai_adapter.py
│   │       ├── gemini.py
│   │       └── registry.py
│   └── models/                   # Pydantic schemas
│       ├── entities.py
│       └── api.py
├── tests/
│   ├── conftest.py
│   ├── routers/
│   ├── services/
│   └── fixtures/
└── pyproject.toml
```

## Команды

```powershell
# Активация venv
.\.venv\Scripts\activate

# Запуск
uvicorn app.main:app --reload --port 8000

# Тесты
pytest                              # все
pytest -v                           # verbose
pytest -m "not slow"                # без медленных
pytest --cov=app --cov-report=html  # с coverage
pytest tests/services/test_ner_pipeline.py::test_specific  # один тест

# Линтинг
ruff check .
ruff check --fix .
ruff format .
mypy app

# Загрузка моделей
python -m spacy download ru_core_news_lg
ollama pull qwen2.5:7b-instruct-q4_K_M
```

## Стиль кода (Python-специфика)

### Type hints
- **Обязательны** для всех публичных функций и методов
- Используй `from __future__ import annotations` если нужны forward references
- Для Pydantic — использовать v2 синтаксис (`model_dump()`, не `dict()`; `model_validate()`, не `parse_obj()`)
- Generics через `from typing import Generic, TypeVar` или PEP 695 (`class Foo[T]:`)

### Async
- FastAPI endpoints — `async def`, кроме случаев когда внутри только sync операции
- Использовать `httpx.AsyncClient` для исходящих HTTP, не `requests`
- Для блокирующих операций (ML-инференс) — `asyncio.to_thread()` или `run_in_executor`

### Структура файла
```python
"""Module docstring describing what this module does."""

from __future__ import annotations

# Standard library
import json
from typing import Any

# Third-party
from fastapi import APIRouter
from pydantic import BaseModel

# Local
from app.config import settings
from app.models.entities import DetectedEntity

# Constants
MAX_TEXT_LENGTH = 10_000_000

# Module logger
import structlog
logger = structlog.get_logger(__name__)


# Classes
class Foo:
    """Google-style docstring.

    Args:
        x: Description.

    Returns:
        Description.

    Raises:
        ValueError: When ...
    """
```

### Pydantic conventions
```python
from pydantic import BaseModel, Field, field_validator

class MyModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    value: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return v.strip()
```

### Логирование (КРИТИЧЕСКИ важно)
```python
# ✅ ХОРОШО — метаданные
logger.info("anonymize.start", session_id=sid, text_length=len(text))

# ❌ ПЛОХО — содержимое
logger.info("anonymize.start", text=text)  # НИКОГДА
logger.info(f"Processing: {text}")          # НИКОГДА
```

### Тесты
- pytest, не unittest
- Использовать fixtures для setup/teardown
- Параметризованные тесты через `@pytest.mark.parametrize`
- Async тесты через `@pytest.mark.asyncio` или `pytest-asyncio` mode auto
- Mock через `unittest.mock` или `pytest-mock`

## Что специфично для backend

### Никогда не логируй
- Текст документов
- Mapping table или её части
- Master key или сессионные ключи
- Полные ответы Cloud LLM
- Содержимое .env

### Всегда проверяй
- Что секреты не оказались в логах (через caplog в тестах)
- Что type hints проходят mypy strict
- Что новые зависимости добавлены в pyproject.toml с обоснованием в коммите
- Что Docker image собирается (`docker build ./backend`)

### Загрузка ML моделей
- spaCy и GLiNER загружаются при старте FastAPI (lifespan handler)
- Ollama вызывается через HTTP, не Python embed
- Модели НЕ должны загружаться в каждом запросе (потеря производительности)
- При недоступности Ollama — graceful degradation: pipeline работает без LLM-слоя

### Обработка ошибок API
- 400 — validation error (с понятным сообщением)
- 404 — session/entity not found
- 413 — payload too large (для больших файлов)
- 415 — unsupported file format
- 500 — internal error (БЕЗ деталей в ответе клиенту, детали в логах)

## Связанные документы

@../CLAUDE.md
@../docs/ARCHITECTURE.md
@../docs/CODE_STYLE.md
@../docs/SECURITY_MODEL.md
@../docs/adr/0002-three-layer-ner-pipeline.md
@../docs/adr/0005-entity-registry-design.md
@../docs/adr/0006-native-llm-adapters-over-unified-shim.md
