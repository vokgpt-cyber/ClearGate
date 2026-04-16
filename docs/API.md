# API Specification — CLEARGATE Backend

REST API + WebSocket для frontend и внешних интеграций.

**Base URL (Alpha):** `http://localhost:8000`
**OpenAPI docs:** `http://localhost:8000/docs` (генерируется автоматически)

## Аутентификация

На текущем этапе (Alpha): нет (single-user, localhost). На MVP+ — JWT через SSO ЕПАМ.

## Endpoints

### Health

#### GET `/health`
Базовый health check. Не требует аутентификации.

**Response 200:**
```json
{
  "status": "ok",
  "version": "0.1.0-alpha",
  "profile": "alpha",
  "timestamp": "2026-04-09T12:00:00Z"
}
```

#### GET `/health/ready`
Readiness check — все ли модели загружены.

**Response 200:**
```json
{
  "ready": true,
  "components": {
    "spacy": "loaded",
    "gliner": "loaded",
    "ollama": "connected",
    "presidio": "ready"
  }
}
```

**Response 503:**
```json
{
  "ready": false,
  "components": {
    "ollama": "unreachable"
  }
}
```

### Sessions

#### POST `/api/sessions`
Создать новую сессию анонимизации.

**Request:**
```json
{
  "locale": "ru",
  "enable_llm_layer": true,
  "custom_entities": ["должность", "название проекта"]
}
```

**Response 201:**
```json
{
  "session_id": "abc123def456",
  "created_at": "2026-04-09T12:00:00Z",
  "expires_at": "2026-04-10T12:00:00Z"
}
```

#### GET `/api/sessions/{id}`
Получить состояние сессии (без mapping table).

**Response 200:**
```json
{
  "session_id": "abc123def456",
  "created_at": "2026-04-09T12:00:00Z",
  "entity_count": 47,
  "stats": {
    "PER": 12,
    "ORG": 5,
    "MON": 8,
    "DATE": 15,
    "RU_INN": 2,
    "RU_PASSPORT": 1,
    "PHONE": 4
  }
}
```

#### DELETE `/api/sessions/{id}`
Закрыть сессию, очистить mapping table.

**Response 204** (no content)

### Documents

#### POST `/api/documents/upload`
Загрузить документ (DOCX/PDF/TXT).

**Request:** `multipart/form-data` с полем `file`

**Response 200:**
```json
{
  "text": "Извлечённый текст документа...",
  "format": "docx",
  "page_count": 12,
  "char_count": 25400
}
```

**Errors:**
- `400` — нет файла
- `413` — файл слишком большой (>50 МБ)
- `415` — неподдерживаемый формат

#### POST `/api/documents/parse-text`
Отправить plain text напрямую (без загрузки файла).

**Request:**
```json
{
  "text": "Текст документа для анализа..."
}
```

**Response:** аналогичен `/upload`.

### Anonymization

#### POST `/api/sessions/{id}/anonymize`
Запустить NER pipeline и получить анонимизированный текст с сущностями.

**Request:**
```json
{
  "text": "Договор между ООО «Ромашка» (ИНН 7707083893) и Иваном Петровым..."
}
```

**Response 200:**
```json
{
  "anonymized_text": "Договор между [ОРГАНИЗАЦИЯ_1] (ИНН [ИНН_1]) и [ЛИЦО_1]...",
  "entities": [
    {
      "id": "ent_001",
      "text": "ООО «Ромашка»",
      "entity_type": "ORG",
      "placeholder": "[ОРГАНИЗАЦИЯ_1]",
      "start": 14,
      "end": 28,
      "score": 0.95,
      "source_layer": "ner"
    },
    {
      "id": "ent_002",
      "text": "7707083893",
      "entity_type": "RU_INN",
      "placeholder": "[ИНН_1]",
      "start": 35,
      "end": 45,
      "score": 1.0,
      "source_layer": "regex"
    },
    {
      "id": "ent_003",
      "text": "Иваном Петровым",
      "entity_type": "PER",
      "placeholder": "[ЛИЦО_1]",
      "start": 50,
      "end": 65,
      "score": 0.92,
      "source_layer": "ner"
    }
  ],
  "stats": {
    "ORG": 1,
    "RU_INN": 1,
    "PER": 1
  }
}
```

#### POST `/api/sessions/{id}/deanonymize`
Заменить плейсхолдеры в произвольном тексте на оригинальные значения.

**Request:**
```json
{
  "text": "Анализ договора показывает, что [ОРГАНИЗАЦИЯ_1] нарушила обязательства перед [ЛИЦО_1]."
}
```

**Response 200:**
```json
{
  "text": "Анализ договора показывает, что ООО «Ромашка» нарушила обязательства перед Иваном Петровым."
}
```

#### PATCH `/api/sessions/{id}/entities/{entity_id}`
Обновить сущность (accept/reject/edit) после ревью пользователем.

**Request:**
```json
{
  "action": "edit",
  "new_value": "ООО «Ромашка-Премиум»"
}
```

`action` принимает: `accept`, `reject`, `edit`. Для `edit` обязательно `new_value`.

**Response 200:**
```json
{ "ok": true }
```

#### POST `/api/sessions/{id}/entities`
Добавить сущность вручную (юрист выделил текст в UI).

**Request:**
```json
{
  "text": "проект Феникс",
  "entity_type": "PROJECT_CODENAME",
  "start": 120,
  "end": 132
}
```

**Response 201:**
```json
{
  "id": "ent_048",
  "placeholder": "[ПРОЕКТ_1]"
}
```

### Mapping export/import

#### GET `/api/sessions/{id}/export-mapping`
Экспортировать зашифрованную mapping table.

**Response 200:** `application/octet-stream` (бинарный blob с шифрованной mapping table)

#### POST `/api/sessions/{id}/import-mapping`
Импортировать ранее экспортированную mapping table.

**Request:** `application/octet-stream`

**Response 200:**
```json
{
  "imported_entities": 47
}
```

### LLM Adapter info

#### GET `/api/llm/providers`
Список доступных LLM провайдеров и моделей.

**Response 200:**
```json
{
  "providers": [
    {
      "id": "claude",
      "name": "Anthropic Claude",
      "available": true,
      "models": [
        {
          "id": "claude-opus-4-6",
          "name": "Claude Opus 4.6",
          "context_window": 1000000,
          "supports_thinking": true,
          "input_cost_per_1m": 5.00,
          "output_cost_per_1m": 25.00
        }
      ]
    }
  ]
}
```

#### POST `/api/llm/estimate-cost`
Оценить стоимость запроса.

**Request:**
```json
{
  "anonymized_text": "...",
  "prompt": "Проанализируй этот договор",
  "provider": "claude",
  "model": "claude-opus-4-6",
  "thinking_level": "high"
}
```

**Response 200:**
```json
{
  "input_tokens": 12500,
  "estimated_output_tokens": 25000,
  "estimated_thinking_tokens": 5000,
  "input_cost_usd": 0.0625,
  "output_cost_usd": 0.625,
  "thinking_cost_usd": 0.125,
  "total_cost_usd": 0.8125
}
```

## WebSocket

### `/ws/stream`
Streaming endpoint для ответов LLM.

**Client → Server (на старте):**
```json
{
  "session_id": "abc123def456",
  "anonymized_text": "...",
  "prompt": "Проанализируй этот договор",
  "provider": "claude",
  "model": "claude-opus-4-6",
  "thinking_level": "high",
  "max_tokens": 8192
}
```

**Server → Client (стрим):**

`thinking_delta` — фрагмент thinking-блока:
```json
{ "type": "thinking_delta", "content": "Анализирую структуру договора..." }
```

`text_delta` — фрагмент основного ответа:
```json
{ "type": "text_delta", "content": "Договор" }
```

`final` — финальный деанонимизированный ответ:
```json
{
  "type": "final",
  "content": "Договор между ООО «Ромашка» и Иваном Петровым содержит...",
  "metadata": {
    "input_tokens": 12500,
    "output_tokens": 23000,
    "model": "claude-opus-4-6",
    "stop_reason": "end_turn"
  }
}
```

`error` — ошибка:
```json
{ "type": "error", "content": "API rate limit exceeded" }
```

После `final` или `error` сервер закрывает соединение.

## Коды ошибок

| Code | Meaning |
|------|---------|
| 400 | Bad request — невалидные данные |
| 401 | Unauthorized — нет токена (на MVP+) |
| 403 | Forbidden — нет прав (на MVP+) |
| 404 | Not found — сессия/сущность не найдена |
| 413 | Payload too large — файл больше лимита |
| 415 | Unsupported media type — формат файла не поддерживается |
| 422 | Unprocessable entity — Pydantic validation failed |
| 429 | Too many requests — rate limit |
| 500 | Internal server error |
| 503 | Service unavailable — модели не загружены |

## Rate limits

| Endpoint | Limit |
|----------|-------|
| `/api/anonymize` | 10 req/min на сессию |
| `/api/llm/estimate-cost` | 60 req/min на сессию |
| `/ws/stream` | 5 параллельных коннектов на сессию |

(На Alpha rate limits отключены — single-user mode.)

## Версионирование API

API версионируется через path prefix: `/api/v1/`, `/api/v2/`, ... На текущем этапе используется `/api/` (без версии = v1). Breaking changes в новой версии будут в `/api/v2/` с одновременной поддержкой обеих в течение переходного периода.
