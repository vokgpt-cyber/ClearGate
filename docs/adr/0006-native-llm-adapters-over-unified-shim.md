# ADR-0006: Native LLM SDKs over unified shim

**Дата:** 2026-04-09
**Статус:** Accepted
**Авторы:** EPAM Legal Dev

## Контекст

CLEARGATE интегрируется с тремя облачными LLM провайдерами: Anthropic Claude, OpenAI GPT, Google Gemini. Каждый провайдер имеет свой SDK с уникальными возможностями (extended thinking у Claude, reasoning у OpenAI o-series, thinking у Gemini).

Два подхода к интеграции:

1. **Unified shim** — использовать библиотеку типа LiteLLM, OpenRouter, или Vercel AI SDK, которая предоставляет единый интерфейс ко всем провайдерам
2. **Нативные SDK** — использовать `anthropic`, `openai`, `google-genai` напрямую с тонким адаптером поверх каждого

## Решение

Использовать **нативные SDK** каждого провайдера за общим абстрактным интерфейсом `LLMAdapter`.

## Альтернативы, которые рассматривались

### LiteLLM (unified shim)
- ✅ Единый API для всех провайдеров
- ✅ Простая миграция между провайдерами
- ❌ Extended thinking / reasoning часто реализованы с задержкой или неполноценно
- ❌ При выходе новых фич у провайдеров приходится ждать обновления LiteLLM
- ❌ Параметры специфичные для провайдера (например, Gemini thought signatures) либо теряются, либо требуют workaround
- ❌ Лишний слой → больше точек отказа

### OpenRouter (proxy-based unified API)
- ✅ Совсем простая интеграция (один OpenAI-совместимый endpoint)
- ✅ Удобно для прототипов
- ❌ Это **proxy через сторонний сервис** — данные проходят через OpenRouter
- ❌ **КРИТИЧЕСКИ НЕДОПУСТИМО** для CLEARGATE: даже анонимизированные данные не должны идти через лишний посредник
- ❌ Reasoning / thinking токены могут не передаваться корректно

### Vercel AI SDK
- ✅ Хорош для Next.js приложений
- ❌ Это TypeScript SDK, а наш LLM gateway — на Python
- ❌ Те же ограничения, что у других unified shim'ов

## Решение в деталях

Базовый интерфейс:
```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from pydantic import BaseModel

class StreamChunk(BaseModel):
    type: Literal["thinking", "text", "done"]
    content: str
    metadata: dict[str, Any] = {}

class CostEstimate(BaseModel):
    input_tokens: int
    estimated_output_tokens: int
    estimated_thinking_tokens: int
    total_cost_usd: float
    breakdown: dict[str, float]

class LLMAdapter(ABC):
    @abstractmethod
    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel,
    ) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    def estimate_cost(
        self,
        text: str,
        model: str,
        thinking_level: ThinkingLevel,
    ) -> CostEstimate: ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...
```

Конкретные реализации:

**ClaudeAdapter** — `anthropic` SDK
```python
import anthropic

class ClaudeAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, ..., thinking_level: ThinkingLevel) -> AsyncIterator[StreamChunk]:
        async with self.client.messages.stream(
            model=model,
            max_tokens=8192,
            thinking={"type": "adaptive", "effort": thinking_level.value},
            messages=[{"role": "user", "content": f"{prompt}\n\n{anonymized_text}"}],
        ) as stream:
            async for event in stream:
                if event.type == "thinking_delta":
                    yield StreamChunk(type="thinking", content=event.delta.thinking)
                elif event.type == "text_delta":
                    yield StreamChunk(type="text", content=event.delta.text)
            yield StreamChunk(type="done", content="")
```

**OpenAIAdapter** — `openai` SDK через **Responses API**
```python
import openai

class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def generate(self, ...) -> AsyncIterator[StreamChunk]:
        # ВАЖНО: Responses API, не Chat Completions —
        # только Responses возвращает reasoning токены для o-series и GPT-5+
        stream = await self.client.responses.create(
            model=model,
            input=f"{prompt}\n\n{anonymized_text}",
            reasoning={"effort": thinking_level.value},
            stream=True,
        )
        async for event in stream:
            if event.type == "response.reasoning.delta":
                yield StreamChunk(type="thinking", content=event.delta)
            elif event.type == "response.output.delta":
                yield StreamChunk(type="text", content=event.delta)
        yield StreamChunk(type="done", content="")
```

**GeminiAdapter** — `google-genai` SDK
```python
from google import genai

class GeminiAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self._thought_signatures: dict[str, str] = {}  # для multi-turn

    async def generate(self, ..., session_id: str) -> AsyncIterator[StreamChunk]:
        config = genai.types.GenerateContentConfig(
            thinking_config=genai.types.ThinkingConfig(
                thinking_level=thinking_level.value,
            ),
        )
        # ВАЖНО: при multi-turn передавать обратно thought signatures
        if session_id in self._thought_signatures:
            config.thought_signature = self._thought_signatures[session_id]

        async for chunk in await self.client.aio.models.generate_content_stream(
            model=model,
            contents=f"{prompt}\n\n{anonymized_text}",
            config=config,
        ):
            if chunk.thought_signature:
                self._thought_signatures[session_id] = chunk.thought_signature
            yield StreamChunk(type="text", content=chunk.text)
        yield StreamChunk(type="done", content="")
```

## Последствия

### Положительные
- **Полный доступ** ко всем фичам каждого провайдера, включая extended thinking, prompt caching, tool use
- **Прямой контроль** над форматом запросов и парсингом ответов
- **Никаких посредников** — данные идут напрямую от backend к API провайдера
- **Безопасность**: меньше supply chain risk (зависим только от официальных SDK)
- **Свежие фичи** доступны сразу после релиза провайдером (не нужно ждать обновления unified shim)

### Отрицательные / компромиссы
- **Больше кода** — три адаптера вместо одной обёртки
- **Дублирование логики** retry, error handling, cost estimation для каждого провайдера
- **Сложнее тестировать** — нужно мокать три SDK
- При добавлении нового провайдера нужно писать новый адаптер с нуля

### Нейтральные
- Зависимость от трёх SDK вместо одного — но все три первоклассные и активно поддерживаются

## Митигация недостатков

- **Общая логика** (retry, timeout, cost calculation, error mapping) выносится в `BaseLLMAdapter` миксин/абстрактный класс
- **Тесты адаптеров** используют записанные ответы (`vcrpy` или собственные fixtures) для воспроизводимости
- **Cost calculation** — отдельный модуль `cost_calculator.py` с актуальной таблицей цен (`docs/llm_pricing.json`)

## Связанные ADR

- Связан с архитектурным разделом 5 (LLM Adapters)

## Ссылки

- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [Anthropic extended thinking docs](https://docs.claude.com/en/docs/build-with-claude/extended-thinking)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [Google GenAI SDK](https://github.com/googleapis/python-genai)
- [Gemini thinking docs](https://ai.google.dev/gemini-api/docs/thinking)
