# Task 07: Claude LLM Adapter (Native SDK)

## Контекст

VELUM использует нативные SDK для каждого LLM-провайдера (см. ADR-0006). Эта задача — реализация ClaudeAdapter с полной поддержкой extended thinking, стриминга и cost estimation. Это первый адаптер; OpenAI и Gemini делаются по аналогии в отдельных задачах.

## Зависимости

- Task 01 (project init)
- Task 06 (нужен SessionManager для контекста)
- Прочитать `docs/adr/0006-native-llm-adapters-over-unified-shim.md`

## Цель

Создать `ClaudeAdapter` за общим интерфейсом `LLMAdapter` с поддержкой Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 и extended thinking.

## Требования

### Базовый интерфейс

```python
# backend/app/services/llm_adapters/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal
from pydantic import BaseModel

ThinkingLevel = Literal["off", "low", "medium", "high", "max"]


class StreamChunk(BaseModel):
    type: Literal["thinking", "text", "done", "error"]
    content: str = ""
    metadata: dict = {}


class CostEstimate(BaseModel):
    input_tokens: int
    estimated_output_tokens: int
    estimated_thinking_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    thinking_cost_usd: float
    total_cost_usd: float


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: Literal["claude", "openai", "gemini"]
    context_window: int
    supports_thinking: bool
    input_cost_per_1m: float
    output_cost_per_1m: float


class LLMAdapter(ABC):
    @abstractmethod
    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel = "high",
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response from LLM."""

    @abstractmethod
    def estimate_cost(
        self,
        text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel = "high",
    ) -> CostEstimate: ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

### Claude adapter

```python
# backend/app/services/llm_adapters/claude.py

from typing import AsyncIterator
import anthropic
import structlog

from app.services.llm_adapters.base import (
    LLMAdapter, StreamChunk, CostEstimate, ModelInfo, ThinkingLevel
)
from app.config import settings

logger = structlog.get_logger()


CLAUDE_MODELS = [
    ModelInfo(
        id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider="claude",
        context_window=1_000_000,
        supports_thinking=True,
        input_cost_per_1m=5.00,
        output_cost_per_1m=25.00,
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider="claude",
        context_window=1_000_000,
        supports_thinking=True,
        input_cost_per_1m=3.00,
        output_cost_per_1m=15.00,
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider="claude",
        context_window=200_000,
        supports_thinking=True,
        input_cost_per_1m=1.00,
        output_cost_per_1m=5.00,
    ),
]


class ClaudeAdapter(LLMAdapter):
    """Native adapter for Anthropic Claude API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str = "claude-opus-4-6",
        thinking_level: ThinkingLevel = "high",
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamChunk]:
        # КРИТИЧЕСКИ: НЕ логировать anonymized_text целиком
        logger.info(
            "claude.generate.start",
            model=model,
            thinking_level=thinking_level,
            text_length=len(anonymized_text),
            prompt_length=len(prompt),
        )

        thinking_config = self._build_thinking_config(thinking_level)
        full_message = f"{prompt}\n\nДокумент:\n{anonymized_text}"

        try:
            async with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                thinking=thinking_config,
                messages=[{"role": "user", "content": full_message}],
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        continue
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "thinking"):
                            yield StreamChunk(type="thinking", content=delta.thinking)
                        elif hasattr(delta, "text"):
                            yield StreamChunk(type="text", content=delta.text)
                    elif event.type == "message_stop":
                        break

                # Финальные метаданные
                final = await stream.get_final_message()
                yield StreamChunk(
                    type="done",
                    content="",
                    metadata={
                        "input_tokens": final.usage.input_tokens,
                        "output_tokens": final.usage.output_tokens,
                        "model": final.model,
                        "stop_reason": final.stop_reason,
                    },
                )
            logger.info("claude.generate.done", model=model)
        except anthropic.APIError as e:
            logger.error("claude.generate.error", model=model, error=str(e))
            yield StreamChunk(type="error", content=str(e))

    def _build_thinking_config(self, level: ThinkingLevel) -> dict | None:
        """Build thinking config for Claude API."""
        if level == "off":
            return None
        return {
            "type": "adaptive",
            "effort": level,
        }

    def estimate_cost(
        self,
        text: str,
        prompt: str,
        model: str = "claude-opus-4-6",
        thinking_level: ThinkingLevel = "high",
    ) -> CostEstimate:
        """Estimate cost using Anthropic token counting."""
        full_message = f"{prompt}\n\n{text}"
        # Для точности использовать count_tokens API когда он доступен,
        # иначе rough estimate (1 token ≈ 3 символа для русского)
        input_tokens = len(full_message) // 3

        # Эвристика для output: ~30% от input для analytical задач
        estimated_output = int(input_tokens * 0.3)
        estimated_thinking = self._estimate_thinking_tokens(input_tokens, thinking_level)

        model_info = next((m for m in CLAUDE_MODELS if m.id == model), CLAUDE_MODELS[0])

        input_cost = (input_tokens / 1_000_000) * model_info.input_cost_per_1m
        output_cost = (estimated_output / 1_000_000) * model_info.output_cost_per_1m
        thinking_cost = (estimated_thinking / 1_000_000) * model_info.output_cost_per_1m

        return CostEstimate(
            input_tokens=input_tokens,
            estimated_output_tokens=estimated_output,
            estimated_thinking_tokens=estimated_thinking,
            input_cost_usd=round(input_cost, 4),
            output_cost_usd=round(output_cost, 4),
            thinking_cost_usd=round(thinking_cost, 4),
            total_cost_usd=round(input_cost + output_cost + thinking_cost, 4),
        )

    def _estimate_thinking_tokens(self, input_tokens: int, level: ThinkingLevel) -> int:
        multipliers = {
            "off": 0.0, "low": 0.1, "medium": 0.25,
            "high": 0.5, "max": 1.0,
        }
        return int(input_tokens * multipliers.get(level, 0.5))

    def list_models(self) -> list[ModelInfo]:
        return CLAUDE_MODELS

    async def health_check(self) -> bool:
        """Check if API is reachable and key is valid."""
        try:
            await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception as e:
            logger.warning("claude.health_check.failed", error=str(e))
            return False
```

## Файлы для создания

```
backend/app/services/llm_adapters/__init__.py
backend/app/services/llm_adapters/base.py
backend/app/services/llm_adapters/claude.py
backend/app/services/llm_adapters/registry.py    # для регистрации всех адаптеров
backend/tests/services/llm_adapters/test_claude_adapter.py
backend/tests/services/llm_adapters/fixtures/claude_responses.json
```

## Тесты

Использовать `pytest-asyncio` и mock для `AsyncAnthropic`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.llm_adapters.claude import ClaudeAdapter

@pytest.mark.asyncio
async def test_claude_generate_streams_text():
    adapter = ClaudeAdapter(api_key="test-key")

    # Mock the stream
    mock_stream = AsyncMock()
    mock_stream.__aenter__.return_value = mock_stream
    mock_stream.__aiter__.return_value = iter([
        MagicMock(type="content_block_delta", delta=MagicMock(text="Hello")),
        MagicMock(type="message_stop"),
    ])
    mock_stream.get_final_message = AsyncMock(return_value=MagicMock(
        usage=MagicMock(input_tokens=10, output_tokens=5),
        model="claude-opus-4-6",
        stop_reason="end_turn",
    ))

    adapter.client.messages.stream = MagicMock(return_value=mock_stream)

    chunks = []
    async for chunk in adapter.generate("test", "prompt"):
        chunks.append(chunk)

    text_chunks = [c for c in chunks if c.type == "text"]
    assert len(text_chunks) == 1
    assert text_chunks[0].content == "Hello"

    done_chunks = [c for c in chunks if c.type == "done"]
    assert len(done_chunks) == 1
    assert done_chunks[0].metadata["input_tokens"] == 10
```

Также:
- Test cost estimation для всех моделей
- Test thinking levels mapping
- Test error handling (API errors → StreamChunk type="error")
- Test list_models
- Опционально: integration test с реальным API (помечен `@pytest.mark.llm`, skip по умолчанию)

## Acceptance Criteria

- [ ] `ClaudeAdapter` реализует `LLMAdapter` интерфейс полностью
- [ ] Все три модели (Opus 4.6, Sonnet 4.6, Haiku 4.5) поддержаны
- [ ] Thinking levels работают (off → max)
- [ ] Стриминг возвращает thinking и text chunks отдельно
- [ ] Cost estimation покрывает input + output + thinking
- [ ] Логи НЕ содержат тексты документов
- [ ] mypy strict без ошибок
- [ ] Tests проходят (mocked)
- [ ] Integration test с реальным API (опц., если есть API key)

## Команды

```powershell
cd backend
pytest tests/services/llm_adapters/test_claude_adapter.py -v

# Integration (требует ANTHROPIC_API_KEY)
pytest tests/services/llm_adapters/ -v -m "llm"
```

## Коммит

```
feat(backend): implement Claude LLM adapter with extended thinking

- Native anthropic SDK (no unified shim)
- Support for Claude Opus 4.6, Sonnet 4.6, Haiku 4.5
- Adaptive extended thinking with effort levels (off/low/med/high/max)
- Streaming with separate thinking_delta and text_delta events
- Cost estimation with thinking token forecast
- Health check endpoint
- No PII in logs

Closes task #7
```
