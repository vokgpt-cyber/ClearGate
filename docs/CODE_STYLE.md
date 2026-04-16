# Code Style Guide — CLEARGATE

## Принципы

1. **Читаемость > краткость.** Код читается в 10 раз чаще, чем пишется.
2. **Явное > неявное.** `from typing import Optional` лучше чем магия.
3. **Согласованность > предпочтения.** Линтер прав, даже если ты не согласен.
4. **Один способ делать вещи.** Если есть несколько способов — выбираем один и держимся.

Code style enforced автоматически через pre-commit hooks. Если код не проходит линтер — он не коммитится.

## Python

### Версия и совместимость
- **Python 3.12+** — обязательно
- Используем новые фичи: PEP 695 (generic syntax), `match` statements, `|` union типы
- НЕ используем legacy: `typing.Optional` (используй `X | None`), `typing.List` (используй `list`)

### Форматирование
- **black** + **ruff format**, line length **100**
- 4 пробела отступа, никаких табов
- LF line endings (даже на Windows — настроено в `.gitattributes`)
- Trailing comma в multi-line literals и function args

### Импорты

```python
# 1. Standard library
import json
import os
from datetime import datetime, UTC
from typing import Any, Literal

# 2. Third-party
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import structlog

# 3. Local
from app.config import settings
from app.models.entities import DetectedEntity, EntityType
from app.services.entity_registry import EntityRegistry
```

Сортировка автоматически через `ruff --select I` (isort).

### Type hints

**Обязательно** для:
- Все публичные функции и методы
- Параметры и возвращаемые значения
- Class attributes (через annotations)

```python
# ✅ Хорошо
def process_text(
    text: str,
    language: Literal["ru", "en"] = "ru",
    max_length: int | None = None,
) -> list[DetectedEntity]:
    ...

# ❌ Плохо
def process_text(text, language="ru", max_length=None):
    ...
```

Для приватных утилит type hints желательны, но не обязательны (mypy не проверяет `_` префиксы strict).

### Docstrings

Google style для всех публичных функций:

```python
def normalize_entity(text: str, entity_type: EntityType) -> str:
    """Normalize entity text to canonical form for registry lookup.

    Performs morphological normalization for Russian names (using pymorphy3)
    and removes legal forms (ООО, АО, etc.) for organizations.

    Args:
        text: Raw entity text from NER pipeline.
        entity_type: Type of entity (PER, ORG, ADDR, etc.).

    Returns:
        Normalized canonical form, suitable for use as a registry key.

    Raises:
        ValueError: If entity_type is not supported.

    Examples:
        >>> normalize_entity("Иванова Ивана Ивановича", "PER")
        'иванов иван иванович'
        >>> normalize_entity("ООО «Ромашка»", "ORG")
        'ромашка'
    """
```

### Naming

| Тип | Стиль | Пример |
|-----|-------|--------|
| Модули | `snake_case` | `entity_registry.py` |
| Классы | `PascalCase` | `EntityRegistry` |
| Функции/методы | `snake_case` | `get_or_create_placeholder` |
| Константы | `UPPER_SNAKE_CASE` | `MAX_TEXT_LENGTH` |
| Приватные | `_leading_underscore` | `_normalize_person` |
| Внутренние модули | `__double_underscore` | (только для name mangling) |

### Async

- FastAPI endpoints — всегда `async def`
- HTTP клиенты — `httpx.AsyncClient`, не `requests`
- Блокирующие операции (ML inference) — `await asyncio.to_thread(...)`
- Никогда не блокируй event loop в async функции

```python
# ✅ Хорошо
async def analyze_text(text: str) -> list[DetectedEntity]:
    # ML inference — потенциально блокирующая операция
    entities = await asyncio.to_thread(spacy_model, text)
    return process(entities)

# ❌ Плохо
async def analyze_text(text: str) -> list[DetectedEntity]:
    entities = spacy_model(text)  # блокирует event loop!
    return process(entities)
```

### Pydantic v2

```python
from pydantic import BaseModel, Field, field_validator

class MyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000_000, description="Text to analyze")
    language: Literal["ru", "en"] = "ru"

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

# Сериализация
data = obj.model_dump()       # ✅ v2
data = obj.model_dump_json()  # ✅ v2
data = obj.dict()             # ❌ v1, deprecated

# Валидация
obj = MyRequest.model_validate(raw)  # ✅ v2
obj = MyRequest.parse_obj(raw)       # ❌ v1, deprecated
```

### Логирование (structlog)

```python
import structlog
logger = structlog.get_logger(__name__)

# ✅ Хорошо — структурированные метаданные
logger.info("anonymize.start", session_id=sid, text_length=len(text))
logger.error("anonymize.failed", session_id=sid, error=str(e), exc_info=True)

# ❌ Плохо — f-strings и PII
logger.info(f"Processing text: {text}")  # PII В ЛОГАХ!
logger.info(f"Session {sid} started")    # лучше структурно
```

### Error handling

```python
# ✅ Хорошо — узкие except, явная обработка
try:
    result = await llm_adapter.generate(text, prompt)
except anthropic.RateLimitError as e:
    logger.warning("llm.rate_limit", provider="claude", retry_after=e.retry_after)
    raise HTTPException(status_code=429, detail="Rate limit exceeded")
except anthropic.APIError as e:
    logger.error("llm.api_error", provider="claude", error=str(e))
    raise HTTPException(status_code=502, detail="LLM provider error")

# ❌ Плохо — голый except
try:
    result = await llm_adapter.generate(text, prompt)
except:
    pass
```

### Линтеры

```toml
# pyproject.toml — уже настроено
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "N", "S", "T20", "SIM", "ARG", "RUF"]

[tool.mypy]
strict = true
```

```powershell
# Запуск
ruff check .
ruff check --fix .
ruff format .
mypy app
```

## TypeScript / React

### Версии
- **TypeScript 5.x** strict mode
- **React 19** с новыми хуками
- **Next.js 15** app router

### Форматирование
- **Prettier** с дефолтами + line length 100
- 2 пробела отступа
- Single quotes для строк, double quotes только в JSX attributes
- Trailing commas везде где можно
- Semicolons обязательны

### Конфигурация
```json
// .prettierrc.json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false,
  "arrowParens": "always",
  "endOfLine": "lf"
}
```

### TypeScript strict mode

```json
// tsconfig.json — обязательные опции
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true
  }
}
```

### Типы

```typescript
// ✅ Хорошо — interface для props
interface EntityHighlighterProps {
  text: string;
  entities: DetectedEntity[];
  onEntityClick: (entity: DetectedEntity) => void;
}

// ✅ Хорошо — discriminated unions
type StreamMessage =
  | { type: 'thinking_delta'; content: string }
  | { type: 'text_delta'; content: string }
  | { type: 'error'; content: string };

// ❌ Плохо — any
function handleMessage(msg: any) { ... }

// ✅ Хорошо — unknown с narrowing
function handleMessage(msg: unknown) {
  if (typeof msg === 'object' && msg !== null && 'type' in msg) { ... }
}
```

### React компоненты

```tsx
// ✅ Хорошо — функциональный компонент с явными props
interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
  disabled?: boolean;
}

export function Button({ label, onClick, variant = 'primary', disabled = false }: ButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`btn btn-${variant}`}
    >
      {label}
    </button>
  );
}

// ❌ Плохо — class components, PropTypes, нет типов
class Button extends React.Component {
  static propTypes = { label: PropTypes.string };
  render() { return <button onClick={this.props.onClick}>{this.props.label}</button>; }
}
```

### Хуки

```typescript
// ✅ Хорошо — кастомные хуки именуются useXxx, возвращают объект с явными именами
export function useEntityRegistry(sessionId: string) {
  const [entities, setEntities] = useState<DetectedEntity[]>([]);
  const [loading, setLoading] = useState(false);

  const addEntity = useCallback((entity: DetectedEntity) => {
    setEntities((prev) => [...prev, entity]);
  }, []);

  return { entities, loading, addEntity };
}

// ❌ Плохо — возврат массива (запутывает порядок)
export function useEntityRegistry(sessionId: string) {
  const [entities, setEntities] = useState([]);
  return [entities, setEntities];  // что куда?
}
```

### Tailwind CSS

```tsx
// ✅ Хорошо — токены через CSS-переменные
<div className="rounded-md bg-bg-elevated p-4 text-text-primary">

// ❌ Плохо — прямые цвета (не переключаются с темами)
<div className="rounded-md bg-white p-4 text-black dark:bg-gray-800 dark:text-white">
```

### i18n

```tsx
// ✅ Хорошо — все строки через t()
import { useTranslation } from 'react-i18next';

export function MyComponent() {
  const { t } = useTranslation();
  return <h1>{t('app.welcome')}</h1>;
}

// ❌ Плохо — хардкоженные строки
export function MyComponent() {
  return <h1>Добро пожаловать в CLEARGATE</h1>;
}
```

### Naming

| Тип | Стиль | Пример |
|-----|-------|--------|
| Файлы компонентов | `PascalCase.tsx` | `SplitScreen.tsx` |
| Файлы хуков | `useXxx.ts` (camelCase) | `useTheme.ts` |
| Файлы утилит | `kebab-case.ts` | `entity-helpers.ts` |
| Компоненты | `PascalCase` | `SplitScreen` |
| Хуки | `useCamelCase` | `useTheme` |
| Функции | `camelCase` | `formatDate` |
| Константы | `UPPER_SNAKE_CASE` | `MAX_TEXT_LENGTH` |
| Типы / Interfaces | `PascalCase` | `DetectedEntity` |

### ESLint config

```json
// .eslintrc.json (упрощённый)
{
  "extends": [
    "next/core-web-vitals",
    "next/typescript",
    "plugin:@typescript-eslint/recommended-strict",
    "prettier"
  ],
  "rules": {
    "@typescript-eslint/no-unused-vars": ["error", { "argsIgnorePattern": "^_" }],
    "@typescript-eslint/consistent-type-imports": "error",
    "react/jsx-key": "error",
    "react-hooks/exhaustive-deps": "warn",
    "no-console": ["warn", { "allow": ["warn", "error"] }]
  }
}
```

## Git коммиты

См. `docs/GIT_WORKFLOW.md` — Conventional Commits полностью описаны там.

Краткая выжимка:
```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

Типы: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `chore`, `security`

## Markdown / Документация

- Заголовки в `#` формате (не `===`)
- Code fences с указанием языка: ` ```python `, ` ```typescript `, ` ```powershell `
- Списки через `-`, не `*`
- Длина строк ≤ 120 символов (но длинные ссылки и таблицы можно)
- Внутренние ссылки в относительном формате: `[Архитектура](docs/ARCHITECTURE.md)`
- Эмодзи 🎯 уместны в README и Roadmap, не в технической документации

## Что НЕЛЬЗЯ делать

### Python
- ❌ Wildcard imports: `from module import *`
- ❌ Mutable default args: `def f(x=[]):` 
- ❌ Голый `except:` без типа
- ❌ `print()` в production коде (только `logger`)
- ❌ Hardcoded paths
- ❌ Магические числа без констант
- ❌ `eval()`, `exec()` (security risk)

### TypeScript / React
- ❌ `any` без обоснования
- ❌ `// @ts-ignore` без `// TODO: fix`
- ❌ Class components (только functional + hooks)
- ❌ Inline functions в JSX `onClick={() => ...}` для часто рендерящихся компонентов
- ❌ Direct DOM манипуляции (только через refs)
- ❌ `dangerouslySetInnerHTML` без явной санитизации
- ❌ `localStorage` для чувствительных данных
- ❌ `console.log` в production коде
- ❌ Hardcoded URLs (использовать env vars)

## Pre-commit hooks

См. `.pre-commit-config.yaml`. Если коммит падает из-за линтера:

```powershell
# Автофикс ruff
cd backend
ruff check --fix .
ruff format .

# Автофикс ESLint
cd frontend
npx eslint --fix src/
npx prettier --write src/

# Повторить коммит
git add .
git commit -m "..."
```
