# ADR-0004: Ollama for local LLM inference

**Дата:** 2026-04-09
**Статус:** Accepted
**Авторы:** EPAM Legal Dev

## Контекст

Третий слой NER pipeline (см. [ADR-0002](0002-three-layer-ner-pipeline.md)) — локальная LLM, которая обрабатывает сложные случаи: кореференцию, составные сущности, контекстную верификацию. Эта LLM должна:

- Работать **полностью локально** (никаких облачных вызовов в этом слое)
- Поддерживать разные размеры моделей в зависимости от профиля развёртывания (Alpha 8 ГБ → Final 80+ ГБ VRAM)
- Хорошо понимать русский язык
- Генерировать структурированный JSON
- Запускаться одной командой, без сложной настройки CUDA/cuDNN
- Иметь простой HTTP API для вызова из Python

Кандидаты:
1. **Ollama** — обёртка над llama.cpp с зоопарком моделей
2. **llama.cpp напрямую**
3. **vLLM**
4. **HuggingFace transformers + PyTorch**
5. **LM Studio**

## Решение

Использовать **Ollama** как runtime для локальной LLM на всех профилях (Alpha/MVP/Final). Модель — Qwen 2.5 в подходящем размере для каждого профиля.

## Альтернативы, которые рассматривались

### llama.cpp напрямую
- ✅ Максимальная производительность
- ✅ Полный контроль
- ❌ Сложнее в установке (компиляция, флаги, CUDA pathways)
- ❌ Нужно самому управлять загрузкой/выгрузкой моделей
- ❌ Нет HTTP API из коробки → нужно писать обёртку

### vLLM
- ✅ Самая быстрая batching и continuous batching
- ✅ Production-grade для high-throughput сценариев
- ❌ Sharp edges на consumer GPU (RTX 4060)
- ❌ Заточен под Linux, на Windows работает через WSL
- ❌ Сложнее, чем нужно для одного-двух запросов в минуту в Alpha

### HuggingFace transformers + PyTorch
- ✅ Знакомый API
- ✅ Огромный выбор моделей
- ❌ Высокий overhead (~5+ ГБ python процесс)
- ❌ Медленнее на CPU/GPU чем GGUF через llama.cpp
- ❌ Требует ручной квантизации для влезания в 8 ГБ

### LM Studio
- ✅ Удобный GUI для тестирования
- ❌ Не open-source ядро, проприетарный продукт
- ❌ Не для production use
- ❌ Сложнее интегрировать в Docker

## Решение в деталях

**Ollama** — это:
- Open-source CLI и HTTP server поверх llama.cpp
- Работает на Windows, macOS, Linux
- Установка одной командой
- Простой API: `ollama pull`, `ollama run`, `ollama serve`
- HTTP API на `http://localhost:11434/api/generate` совместим с OpenAI-подобной схемой
- Управление загрузкой/выгрузкой моделей автоматическое
- Поддержка GGUF формата (квантизованные модели)

**Выбор модели — Qwen 2.5** по профилям:

| Профиль | Модель | VRAM | Обоснование |
|---------|--------|------|-------------|
| Alpha | `qwen2.5:7b-instruct-q4_K_M` | ~5 ГБ | Помещается в 8 ГБ RTX 4060 с запасом для KV-cache. Одна из лучших моделей русского языка в этом классе. |
| MVP | `qwen2.5:32b-instruct-q4_K_M` | ~20 ГБ | Использует ~80% VRAM RTX 3090. Качество приближается к GPT-4o на русском. |
| Final | `qwen2.5:72b-instruct` (FP16) или DeepSeek-V3 / fine-tuned | 80+ ГБ | На кластере с A100/H200 — топовый open-source. В перспективе заменяется fine-tuned моделью на корпусе ЕПАМ. |

**Почему Qwen 2.5, а не Llama 3.x:**
- Qwen 2.5 явно обучен на большом корпусе русского языка (Llama 3 не включает русский в официально поддерживаемые)
- Qwen лучше следует инструкциям и генерирует структурированный JSON
- Apache 2.0 лицензия позволяет коммерческое использование
- Бенчмарки на русскоязычных задачах стабильно показывают преимущество Qwen 2.5 над Llama 3 в этих размерах

**Почему не Mistral / Mixtral:**
- Слабее на русском языке
- Бо́льшие требования к VRAM при сопоставимом качестве

## Последствия

### Положительные
- Установка Ollama — одна команда (`winget install Ollama.Ollama`)
- Загрузка модели — одна команда (`ollama pull qwen2.5:7b-instruct-q4_K_M`)
- Простой HTTP API легко вызывать из Python (`ollama` или `httpx`)
- Один и тот же runtime на всех трёх профилях, меняется только модель
- Управление моделями (выгрузка из VRAM при простое) — автоматическое
- Поддержка structured output через `format=json`
- Активная разработка, поддержка новых моделей быстро добавляется

### Отрицательные / компромиссы
- Чуть медленнее, чем чистый llama.cpp с тонкой настройкой (но разница незначительна для наших объёмов)
- Не для high-throughput production (нужно vLLM или Triton). Это OK, поскольку Final тоже не требует тысячи RPS — VELUM это interactive use case
- Ollama — обёртка → если она забагует на новой ОС, нужно ждать фикс

### Нейтральные
- Зависимость от Ollama project (но open-source, MIT лицензия, активная команда)

## Интеграция

```python
import ollama
import json

async def classify_with_local_llm(text: str, candidates: list[Entity]) -> list[Entity]:
    """Verify and refine entity candidates using local LLM."""
    prompt = build_verification_prompt(text, candidates)

    response = await ollama.AsyncClient().generate(
        model=settings.OLLAMA_MODEL,
        prompt=prompt,
        format="json",
        options={"temperature": 0.0},  # детерминизм
    )

    result = json.loads(response["response"])
    return [Entity(**e) for e in result["entities"]]
```

## Связанные ADR

- [ADR-0002](0002-three-layer-ner-pipeline.md) — три слоя pipeline
- [ADR-0003](0003-presidio-as-orchestrator.md) — Presidio для слоёв 1-2

## Ссылки

- [Ollama](https://ollama.com/)
- [Qwen 2.5 на Hugging Face](https://huggingface.co/Qwen)
- [Qwen 2.5 GGUF на Ollama](https://ollama.com/library/qwen2.5)
- [Running Qwen2.5 quantized on 8GB VRAM](https://markaicode.com/qwen25-quantized-gguf-8gb-vram/)
