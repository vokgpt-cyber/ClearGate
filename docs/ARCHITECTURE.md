# VELUM — Архитектура системы

**Версия документа:** 1.0
**Дата:** Апрель 2026
**Статус:** Активный

## Содержание

1. [Высокоуровневый обзор](#1-высокоуровневый-обзор)
2. [Компоненты системы](#2-компоненты-системы)
3. [Pipeline анонимизации](#3-pipeline-анонимизации)
4. [EntityRegistry и консистентный маппинг](#4-entityregistry-и-консистентный-маппинг)
5. [LLM-адаптеры](#5-llm-адаптеры)
6. [Frontend архитектура](#6-frontend-архитектура)
7. [Поток данных](#7-поток-данных)
8. [Безопасность по уровням](#8-безопасность-по-уровням)
9. [Масштабирование](#9-масштабирование)

---

## 1. Высокоуровневый обзор

VELUM — клиент-серверное приложение, работающее как desktop-app через Tauri shell. Серверная часть может работать локально (Alpha/MVP) или в дата-центре ЕПАМ (Final).

```
┌──────────────────────────────────────────────────────────────────┐
│                        VELUM Desktop (Tauri)                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              React + Next.js Frontend                      │ │
│  │  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐   │ │
│  │  │ SplitScreen │ │  LLMPanel    │ │ EntityNavigator  │   │ │
│  │  └─────────────┘ └──────────────┘ └──────────────────┘   │ │
│  │  ┌─────────────────────────────────────────────────────┐ │ │
│  │  │  i18n (RU/EN) │ Theme (light/dark) │ Monaco Editor │ │ │
│  │  └─────────────────────────────────────────────────────┘ │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           │ HTTP/WebSocket                       │
└───────────────────────────┼──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│                    FastAPI Backend (Python 3.12)                 │
│                                                                  │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │   Routers    │  │    Services     │  │     Models       │   │
│  │              │  │                 │  │                  │   │
│  │ /documents   │  │ NER Pipeline    │  │ Pydantic schemas │   │
│  │ /anonymize   │  │ EntityRegistry  │  │                  │   │
│  │ /llm         │  │ LLM Adapters    │  │                  │   │
│  │ /sessions    │  │ DocProcessor    │  │                  │   │
│  │ /ws/stream   │  │ Crypto          │  │                  │   │
│  └──────────────┘  └────────┬────────┘  └──────────────────┘   │
└───────────────────────────────┼──────────────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
┌───────▼────────┐    ┌─────────▼─────────┐    ┌────────▼─────────┐
│  Presidio +    │    │   Ollama          │    │  Cloud LLM APIs  │
│  spaCy +       │    │   (Qwen 2.5)      │    │  Claude/GPT/     │
│  GLiNER        │    │                   │    │  Gemini          │
│                │    │   Local LLM       │    │                  │
│  NER Layer     │    │   (трудные кейсы) │    │  (анонимный      │
│                │    │                   │    │   текст only)    │
└────────────────┘    └───────────────────┘    └──────────────────┘
        ↑                       ↑
        │                       │
        └───────── on-premise ──┘
```

## 2. Компоненты системы

### 2.1 Backend (Python/FastAPI)

| Модуль | Ответственность |
|--------|----------------|
| `app/main.py` | FastAPI app, lifespan events (загрузка моделей при старте) |
| `app/routers/documents.py` | Загрузка/парсинг DOCX/PDF/TXT |
| `app/routers/anonymize.py` | Запуск pipeline, возврат сущностей и маппинга |
| `app/routers/llm.py` | Gateway к Cloud LLM, REST + WebSocket |
| `app/routers/sessions.py` | Управление сессиями (in-memory + опц. шифрованный disk cache) |
| `app/services/ner_pipeline.py` | Оркестрация трёх слоёв NER |
| `app/services/regex_recognizers.py` | Российские PII regex с валидацией |
| `app/services/entity_registry.py` | Реестр сущностей, нормализация, маппинг |
| `app/services/llm_adapters/` | Нативные адаптеры Claude/OpenAI/Gemini |
| `app/services/doc_processor.py` | Парсинг DOCX (python-docx), PDF (PyMuPDF) |
| `app/services/chunker.py` | Чанкинг больших документов |
| `app/services/crypto.py` | AES-256-GCM шифрование mapping table |
| `app/models/` | Pydantic v2 схемы |
| `app/config.py` | Настройки (профиль alpha/mvp/final, пути моделей) |

### 2.2 Frontend (Tauri + Next.js)

| Компонент | Ответственность |
|-----------|----------------|
| `src-tauri/` | Rust-shell, capability config, window management |
| `src/app/` | Next.js app router (статический экспорт для Tauri) |
| `src/components/SplitScreen.tsx` | Главный split-view с синхронной прокруткой |
| `src/components/EntityHighlighter.tsx` | Подсветка сущностей в тексте |
| `src/components/EntityNavigator.tsx` | Боковая панель со списком сущностей |
| `src/components/EntityPopover.tsx` | Accept/reject/edit при клике |
| `src/components/LLMPanel.tsx` | Выбор провайдера/модели/thinking/промпта |
| `src/components/DiffViewer.tsx` | Monaco-based diff ответа LLM |
| `src/components/CommandPalette.tsx` | ⌘K палитра |
| `src/components/ThemeToggle.tsx` | Переключатель light/dark |
| `src/components/LocaleToggle.tsx` | Переключатель RU/EN |
| `src/hooks/` | useAnonymize, useLLMStream, useTheme, useLocale |
| `src/lib/i18n.ts` | i18next config с двумя локалями |
| `src/lib/colors.ts` | Палитра для типов сущностей |

## 3. Pipeline анонимизации

Pipeline состоит из трёх последовательных слоёв; каждый слой добавляет сущности в общий результат и закрывает слабости предыдущего.

### Слой 1 — Regex (Presidio PatternRecognizer)

Самый быстрый и точный слой для структурированных данных. Каждый российский идентификатор имеет чёткий формат с контрольной суммой:

| Сущность | Формат | Валидация |
|----------|--------|-----------|
| ИНН (физ. лицо) | 12 цифр | Контрольные суммы 11/12 |
| ИНН (юр. лицо) | 10 цифр | Контрольная сумма 10 |
| ОГРН | 13 цифр | Mod 11 |
| СНИЛС | XXX-XXX-XXX XX | Алгоритм ПФР |
| Паспорт РФ | XXXX XXXXXX | Допустимые серии |
| Банковский счёт | 20 цифр | Контрольный ключ по БИК |
| Телефон | +7XXXXXXXXXX | Нормализация |
| Email | RFC 5322 | Стандартный regex |
| Дата | ДД.ММ.ГГГГ | Валидация диапазона |
| Номер дела | А40-12345/2026 | Шаблон арбитражного дела |

Каждый PatternRecognizer регистрируется в Presidio с **русскими контекстными словами** («паспорт», «ИНН», «телефон»), что повышает confidence score, когда поблизости есть подсказка.

### Слой 2 — NER

**spaCy ru_core_news_lg** как основной NLP engine для Presidio: распознаёт PER, LOC, ORG с F1 ≈ 93% на бенчмарке Nerus. Работает на CPU, ~540 МБ.

**GLiNER** (Medium для Alpha, Large для MVP/Final) — zero-shot модель для кастомных типов сущностей. Не требует дообучения: задаём метки `["должность", "сумма контракта", "наименование суда", "кодовое название проекта"]` — и модель их находит.

**Natasha/Yargy** — rule-based извлечение для специфики русского языка: морфологический разбор, нормализация имён и компаний.

### Слой 3 — Локальная LLM

Запускается через Ollama. Модель зависит от профиля развёртывания (см. `config.py`):

| Профиль | Модель | VRAM |
|---------|--------|------|
| Alpha | Qwen 2.5 7B Q4_K_M | ~5 ГБ |
| MVP | Qwen 2.5 32B Q4_K_M | ~20 ГБ |
| Final | Qwen 2.5 72B FP16 / DeepSeek-V3 / fine-tuned | 80+ ГБ |

LLM решает задачи, недоступные предыдущим слоям:
- **Кореференция** («он», «указанная компания» → конкретная сущность)
- **Сложные составные сущности** («генеральный директор ООО «Ромашка» Иванов И.И.»)
- **Контекстная верификация** (отсев ложных срабатываний предыдущих слоёв)

LLM получает текст с уже размеченными кандидатами и возвращает структурированный JSON через function calling.

## 4. EntityRegistry и консистентный маппинг

Ключевое требование — **«Иван Петров» должен ВСЕГДА заменяться на `[ЛИЦО_1]`** во всём документе, в любых падежах и формах.

```
┌─────────────────────────────────────────────┐
│           EntityRegistry                    │
├─────────────────────────────────────────────┤
│                                             │
│  Реестр (in-memory, AES-256-GCM):          │
│  ┌──────────────────┬───────────────────┐  │
│  │ Original         │ Placeholder       │  │
│  ├──────────────────┼───────────────────┤  │
│  │ Иван Петров      │ [ЛИЦО_1]          │  │
│  │ И.И. Петрову     │ [ЛИЦО_1]          │  │
│  │ Петрова           │ [ЛИЦО_1]          │  │
│  │ ООО "Ромашка"    │ [ОРГАНИЗАЦИЯ_1]   │  │
│  │ 1 500 000 руб.   │ [СУММА_1]         │  │
│  └──────────────────┴───────────────────┘  │
│                                             │
│  Нормализация:                              │
│  • pymorphy3 (морфология)                   │
│  • Natasha (правила имён)                   │
│  • Левенштейн (нечёткий поиск)              │
│                                             │
└─────────────────────────────────────────────┘
```

**Алгоритм:**
1. При обнаружении сущности — нормализовать (привести к именительному падежу, нижний регистр)
2. Поиск в реестре: точное совпадение → существующий placeholder
3. Нечёткий поиск (Левенштейн ≤ 2 + правила имён): «Иванов И.И.» = «Иванов Иван Иванович»
4. Если совпадений нет — генерация нового placeholder: `[ТИП_N]` где N — инкрементальный счётчик по типу

**Хранение:**
- В оперативной памяти, защищённой `mlock()` от выгрузки в swap
- Шифрование AES-256-GCM с сессионным ключом (HKDF от мастер-ключа)
- При закрытии сессии — `sodium_memzero` для гарантированной очистки
- Опциональный шифрованный disk cache с автоудалением через настраиваемый TTL

Подробнее: [`adr/0005-entity-registry-design.md`](adr/0005-entity-registry-design.md), [`adr/0007-aes-256-gcm-for-mapping-table.md`](adr/0007-aes-256-gcm-for-mapping-table.md).

## 5. LLM-адаптеры

VELUM использует **нативные SDK** каждого провайдера, а не unified shim'ы (LiteLLM, OpenRouter и т.п.). Причина — нужен полный доступ к extended thinking / reasoning у каждого вендора, который unified shim'ы либо теряют, либо реализуют с задержкой.

Базовый интерфейс:
```python
class LLMAdapter(ABC):
    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel,
    ) -> AsyncIterator[StreamChunk]: ...

    def estimate_cost(
        self,
        text: str,
        model: str,
        thinking_level: ThinkingLevel,
    ) -> CostEstimate: ...
```

Реализации:
- **`ClaudeAdapter`** — `anthropic` SDK, `thinking={"type": "adaptive", "effort": "high"}`, SSE парсинг `thinking_delta` + `text_delta`
- **`OpenAIAdapter`** — `openai` SDK через **Responses API** (Chat Completions API не возвращает reasoning токены), `reasoning.effort`
- **`GeminiAdapter`** — `google-genai` SDK, `thinking_level` + thought signatures для multi-turn

Подробнее: [`adr/0006-native-llm-adapters-over-unified-shim.md`](adr/0006-native-llm-adapters-over-unified-shim.md).

## 6. Frontend архитектура

```
┌─────────────────────────────────────────────────────────┐
│                    Tauri App Window                     │
├─────────────────────────────────────────────────────────┤
│  Header: [VELUM logo] [Lang RU/EN] [Theme ☀/🌙] [User] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────┐  ┌──────────────────────────────────────┐ │
│  │         │  │                                       │ │
│  │ Sidebar │  │      Main content area               │ │
│  │         │  │                                       │ │
│  │ - New   │  │  ┌─────────────┬─────────────────┐  │ │
│  │ - Hist  │  │  │  Original   │  Anonymized /   │  │ │
│  │ - Sett  │  │  │  (left)     │  LLM response   │  │ │
│  │         │  │  │             │  (right)        │  │ │
│  │         │  │  │  Highlighted│  Placeholders / │  │ │
│  │         │  │  │  entities   │  diff view      │  │ │
│  │         │  │  └─────────────┴─────────────────┘  │ │
│  │         │  │                                       │ │
│  │         │  │  ┌─────────────────────────────────┐ │ │
│  │         │  │  │ LLM Panel (provider/model/      │ │ │
│  │         │  │  │ thinking/prompt/cost estimate)  │ │ │
│  │         │  │  └─────────────────────────────────┘ │ │
│  └─────────┘  └──────────────────────────────────────┘ │
│                                                         │
│  Entity Navigator (collapsible right sidebar)           │
└─────────────────────────────────────────────────────────┘
```

**State management:** React Context для темы и локали, Zustand или React Query для серверного состояния (сессии, сущности, ответы LLM).

**Streaming:** WebSocket подключение к `/ws/stream`, токены LLM приходят в реальном времени, при завершении бэкенд возвращает финальный деанонимизированный ответ отдельным сообщением.

**Цветовое кодирование сущностей** — 8 категорий, каждая с контрастными вариантами для светлой и тёмной темы (см. `lib/colors.ts`). Все комбинации проверены на WCAG AA 4.5:1, палитра безопасна для дальтоников.

## 7. Поток данных

```
1. Юрист загружает документ (DOCX/PDF/TXT)
       │
       ▼
2. POST /api/documents/upload
   → DocProcessor парсит → plain text + структура
       │
       ▼
3. POST /api/anonymize
   → NER pipeline (Regex → spaCy → GLiNER → Qwen)
   → EntityRegistry (нормализация, маппинг, шифрование)
   → Возврат: { anonymized_text, entities[], session_id }
       │
       ▼
4. UI: SplitScreen — юрист ревьюит сущности
   → Accept/Reject/Edit/Add
       │
       ▼
5. Юрист настраивает запрос (LLMPanel)
   → Выбор провайдера, модели, thinking, промпта
   → Cost estimation в реальном времени
       │
       ▼
6. WS /ws/stream
   → Backend выбирает адаптер
   → Стрим токенов от Cloud LLM
   → Frontend отображает ответ инкрементально
       │
       ▼
7. По завершении стрима:
   → EntityRegistry.deanonymize(response)
   → Финальное сообщение с реальными данными
       │
       ▼
8. UI: правая панель показывает деанонимизированный ответ
   → Если был документ на правку — diff с оригиналом
```

## 8. Безопасность по уровням

| Уровень | Защита |
|---------|--------|
| **Сетевой** | TLS 1.3 для всех внешних API. Отсутствие исходящих соединений из Backend, кроме разрешённых LLM endpoints |
| **Транспортный** | Tauri shell ограничивает capabilities Frontend → Backend |
| **Памяти** | mlock() для mapping table, sodium_memzero при очистке |
| **Хранения** | AES-256-GCM с сессионным ключом из HKDF. Disk cache опционален и зашифрован |
| **Логирования** | Whitelist полей: timestamp, user_id, action_type, doc_id, anonymized fragments. Никогда: оригинальный текст, mapping, ключи |
| **Идентификации** | RBAC (8 ролей) — добавляется в v2.0. На Alpha — single-user |
| **Аудита** | Append-only encrypted journal с hash-chain — добавляется в v2.0 |

Подробнее: [`SECURITY_MODEL.md`](SECURITY_MODEL.md).

## 9. Масштабирование

Архитектура линейно масштабируется через профили развёртывания (`config.py`):

| | Alpha | MVP | Final |
|---|---|---|---|
| Локальная LLM | Qwen 7B | Qwen 32B | Qwen 72B / DeepSeek-V3 |
| Параллельных воркеров FastAPI | 1 | 2–3 | 10+ |
| Workers Frontend | 1 (Tauri) | 1 (Tauri) | N (web app) |
| GPU | 1× RTX 4060 | 1× RTX 3090 | 2–4× A100/H200 |
| Хранилище состояния | In-memory | In-memory | Redis |
| База аудита | — | SQLite | PostgreSQL |
| Развёртывание | Docker Compose | Docker Compose | Kubernetes |

**Один и тот же код** работает на всех трёх уровнях. Меняются только размеры моделей, количество воркеров и инфраструктура. Это решение специально заложено: профиль выбирается через переменную `VELUM_PROFILE` (alpha/mvp/final), всё остальное — в `config.py`.
