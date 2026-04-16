# Testing Strategy — CLEARGATE

## Принципы

1. **Тесты — это safety net для рефакторинга.** Без них вайб-кодинг быстро превращается в кладбище багов.
2. **Тестируется поведение, не реализация.** Изменение реализации без изменения поведения не должно ломать тесты.
3. **Фокус на бизнес-логике.** Тесты для NER, EntityRegistry, адаптеров — критичны. Тесты на CSS — нет.
4. **Метрики качества важнее coverage.** 100% coverage с тривиальными ассертами хуже, чем 70% с осмысленными.

## Уровни тестирования

```
        ┌──────────────────┐
        │       E2E        │  ← UI workflow через Playwright (опционально)
        │   (smoke only)   │     5-10 сценариев, ручной запуск
        └──────────────────┘
       ┌────────────────────┐
       │    Integration     │  ← FastAPI endpoints через TestClient
       │     (key flows)    │     ~30 тестов, в CI на pre-commit
       └────────────────────┘
     ┌────────────────────────┐
     │       Unit             │  ← Core логика: NER, registry, crypto, adapters
     │    (всё критичное)     │     ~200+ тестов, должны проходить за <30s
     └────────────────────────┘
```

## Backend (Python + pytest)

### Структура
```
backend/tests/
├── conftest.py                    # Общие fixtures
├── unit/
│   ├── services/
│   │   ├── test_regex_recognizers.py
│   │   ├── test_checksum_validators.py
│   │   ├── test_entity_registry.py
│   │   ├── test_entity_normalizer.py
│   │   ├── test_crypto.py
│   │   └── test_chunker.py
│   ├── llm_adapters/
│   │   ├── test_claude_adapter.py
│   │   ├── test_openai_adapter.py
│   │   └── test_gemini_adapter.py
│   └── models/
│       └── test_entities.py
├── integration/
│   ├── test_ner_pipeline_full.py  # с реальными моделями
│   └── routers/
│       ├── test_health.py
│       ├── test_sessions.py
│       ├── test_documents.py
│       ├── test_anonymize.py
│       └── test_llm_ws.py
└── fixtures/
    ├── synthetic_pii.json         # Синтетические PII
    ├── sample_legal_texts.json    # Юридические документы
    ├── claude_responses/          # Записанные ответы LLM
    └── docs/                      # Тестовые DOCX/PDF
```

### Запуск

```powershell
cd backend
.\.venv\Scripts\activate

# Все тесты
pytest

# Только unit
pytest tests/unit/

# Без медленных
pytest -m "not slow"

# С coverage
pytest --cov=app --cov-report=html --cov-report=term-missing
start htmlcov/index.html

# Один файл
pytest tests/unit/services/test_entity_registry.py -v

# Один тест
pytest tests/unit/services/test_entity_registry.py::test_consistent_placeholder -v
```

### Markers
```python
import pytest

@pytest.mark.unit
def test_inn_validation():
    ...

@pytest.mark.integration
def test_full_pipeline():
    ...

@pytest.mark.slow
def test_processing_large_document():
    ...

@pytest.mark.llm  # требует API ключ
def test_claude_real_call():
    ...

@pytest.mark.ner  # требует загруженные модели
def test_spacy_russian():
    ...
```

Запуск с фильтрами:
```powershell
pytest -m "unit"               # только unit
pytest -m "not llm"            # без LLM-вызовов
pytest -m "ner and not slow"   # NER, но не медленные
```

### Coverage goals

| Модуль | Цель |
|--------|------|
| `app/services/regex_recognizers.py` | 95%+ |
| `app/services/checksum_validators.py` | 100% |
| `app/services/entity_registry.py` | 90%+ |
| `app/services/crypto.py` | 100% |
| `app/services/llm_adapters/` | 80%+ |
| `app/routers/` | 80%+ |
| `app/services/ner_pipeline.py` | 70% (часть требует моделей) |
| **Общее** | **≥ 75%** |

### Ключевые fixtures

```python
# conftest.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.entity_registry import EntityRegistry

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

@pytest.fixture
def master_key() -> bytes:
    return b"0" * 32  # тестовый ключ, не для production!

@pytest.fixture
def registry(master_key: bytes) -> EntityRegistry:
    return EntityRegistry(
        master_key=master_key,
        session_id="test-session",
        locale="ru",
    )

@pytest.fixture
def synthetic_legal_text() -> str:
    return """ООО «Ромашка» (ИНН 7707083893) в лице Иванова И.И.
    заключило договор с Петровым Петром Петровичем на сумму
    1 500 000 рублей до 31.12.2026."""
```

### Метрики качества NER

Для NER pipeline нужны не unit-тесты, а **метрические** тесты на корпусе:

```python
# tests/integration/test_ner_metrics.py

import json
from pathlib import Path

def test_ner_pipeline_recall(ner_pipeline):
    """Pipeline должен находить ≥95% сущностей на synthetic корпусе."""
    corpus = json.loads(Path("tests/fixtures/sample_legal_texts.json").read_text(encoding="utf-8"))

    total_expected = 0
    total_found = 0

    for sample in corpus:
        entities = await ner_pipeline.analyze(sample["text"], language="ru")
        expected = sample["expected_entities"]

        for exp in expected:
            total_expected += 1
            for found in entities:
                if found.entity_type == exp["type"] and exp["text"] in found.text:
                    total_found += 1
                    break

    recall = total_found / total_expected
    assert recall >= 0.95, f"Recall {recall:.2%} below threshold"
```

### Логи без PII (test для проверки)

```python
def test_anonymize_endpoint_does_not_log_text(client, caplog):
    """API должен логировать метаданные, но не содержимое."""
    secret_text = "Иван Петров заключил договор"
    response = client.post(
        "/api/sessions/test-id/anonymize",
        json={"text": secret_text},
    )

    # Проверяем что текст НЕ попал в логи
    log_text = " ".join(record.message for record in caplog.records)
    assert "Иван Петров" not in log_text
    assert secret_text not in log_text
```

## Frontend (TypeScript + Vitest)

### Структура
```
frontend/src/
├── components/
│   └── __tests__/
│       ├── SplitScreen.test.tsx
│       ├── EntityHighlighter.test.tsx
│       ├── EntityPopover.test.tsx
│       ├── LLMPanel.test.tsx
│       ├── ProviderSelector.test.tsx
│       ├── ThemeToggle.test.tsx
│       └── LocaleToggle.test.tsx
├── hooks/
│   └── __tests__/
│       ├── useTheme.test.ts
│       ├── useLocale.test.ts
│       ├── useLLMStream.test.ts
│       └── useEntityRegistry.test.ts
└── lib/
    └── __tests__/
        ├── api.test.ts
        └── i18n-parity.test.ts
```

### Запуск
```powershell
cd frontend
npm test                       # все тесты
npm test -- --watch            # watch mode
npm test SplitScreen           # фильтр
npm test -- --coverage         # с coverage
```

### Vitest config
```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['**/__tests__/**', '**/node_modules/**'],
    },
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
});
```

### Пример теста

```tsx
// SplitScreen.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import i18n from '@/lib/i18n';
import { SplitScreen } from '../SplitScreen';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);

describe('SplitScreen', () => {
  it('renders both panels', () => {
    renderWithI18n(
      <SplitScreen
        originalText="Hello"
        anonymizedText="Hello"
        entities={[]}
        onEntityUpdate={vi.fn()}
        onEntityAdd={vi.fn()}
      />
    );
    const panels = screen.getAllByText('Hello');
    expect(panels).toHaveLength(2);
  });

  it('calls onEntityUpdate when entity is clicked and accepted', async () => {
    const onUpdate = vi.fn();
    renderWithI18n(
      <SplitScreen
        originalText="Иван Петров заключил..."
        anonymizedText="[ЛИЦО_1] заключил..."
        entities={[{
          id: 'e1',
          text: 'Иван Петров',
          entity_type: 'PER',
          placeholder: '[ЛИЦО_1]',
          start: 0,
          end: 11,
          score: 0.95,
          source_layer: 'ner',
        }]}
        onEntityUpdate={onUpdate}
        onEntityAdd={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText('Иван Петров'));
    fireEvent.click(screen.getByLabelText(/принять/i));

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'e1' }),
      'accept',
      undefined
    );
  });
});
```

### i18n parity test (важно!)

```typescript
// lib/__tests__/i18n-parity.test.ts
import { describe, it, expect } from 'vitest';
import ru from '@/lib/locales/ru.json';
import en from '@/lib/locales/en.json';

function getKeys(obj: Record<string, any>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return typeof v === 'object' && !Array.isArray(v)
      ? getKeys(v, key)
      : [key];
  });
}

describe('i18n locales parity', () => {
  it('ru and en dictionaries have identical keys', () => {
    const ruKeys = getKeys(ru as any).sort();
    const enKeys = getKeys(en as any).sort();
    expect(ruKeys).toEqual(enKeys);
  });
});
```

## E2E (опционально, для MVP+)

Playwright для критичных user flows:

```typescript
// e2e/anonymize-flow.spec.ts
import { test, expect } from '@playwright/test';

test('full anonymization flow', async ({ page }) => {
  await page.goto('http://localhost:3000');

  // Создать сессию
  await page.click('text=Новая сессия');

  // Загрузить документ
  await page.setInputFiles('input[type=file]', './fixtures/sample.docx');

  // Дождаться анализа
  await expect(page.locator('text=Найдено сущностей')).toBeVisible();

  // Принять все
  await page.click('text=Принять все');

  // Выбрать модель
  await page.click('text=Claude');
  await page.click('text=Опус 4.6');

  // Отправить
  await page.fill('textarea[name=prompt]', 'Проанализируй');
  await page.click('text=Отправить');
  await page.click('text=Подтвердить');

  // Дождаться ответа
  await expect(page.locator('text=Анализ договора')).toBeVisible({ timeout: 60000 });
});
```

## CI (когда появится)

На текущем этапе CI нет. Когда появится — как минимум:
1. `pytest` (без `-m llm`)
2. `npm test`
3. `ruff check`, `mypy`, `eslint`, `tsc --noEmit`
4. `pre-commit run --all-files`

## Что НЕ тестируем

- Тривиальные геттеры/сеттеры
- Сторонние библиотеки (Presidio, FastAPI, React) — у них свои тесты
- CSS / визуальный дизайн (только через визуальную проверку)
- Конкретные форматы вывода LLM (только что вызывается с правильными параметрами)

## Регрессионный корпус

`tests/fixtures/sample_legal_texts.json` — synthetic корпус юридических текстов с разметкой ожидаемых сущностей. **Никогда не использовать реальные клиентские документы.** Все примеры — синтетические, созданные специально для тестов.

При обнаружении бага в проде:
1. Воспроизвести его на минимальном synthetic примере
2. Добавить пример в корпус
3. Убедиться, что тест на этот пример падает
4. Исправить баг
5. Убедиться, что тест проходит
6. Закоммитить тест и фикс одним PR/задачей
