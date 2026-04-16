# Contributing to CLEARGATE

CLEARGATE разрабатывается одним разработчиком в режиме вайб-кодинга через Claude Code, но документация и процессы поддерживаются на enterprise-уровне для будущего масштабирования. Этот документ фиксирует правила, которые сам разработчик соблюдает при работе с проектом, и которые Claude Code должен соблюдать при выполнении задач.

## Перед началом работы

1. Прочитай [`CLAUDE.md`](CLAUDE.md) — главный файл проекта
2. Прочитай [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — архитектурный обзор
3. Прочитай релевантные ADR в [`docs/adr/`](docs/adr/)
4. Если работаешь над задачей из roadmap — прочитай соответствующий файл в [`docs/tasks/`](docs/tasks/)

## Workflow

### Перед каждой задачей
```powershell
# 1. Бэкап текущего состояния
.\scripts\backup.ps1

# 2. Убедись, что ты на main и нет unstaged изменений
git status

# 3. Создай feature-ветку
git checkout -b task/NN-short-description
```

### Во время работы
- Часто коммить мелкими логическими единицами
- Запускай тесты после каждого значимого изменения
- Не оставляй закомментированный код
- Не оставляй `print()` / `console.log()` отладочных вызовов
- Используй `TODO(name): описание` для отложенных задач

### Перед коммитом
```powershell
# Backend
cd backend
ruff check --fix .
ruff format .
mypy app
pytest -x

# Frontend
cd frontend
npm run lint:fix
npm run format
npm test
```

### Коммиты — Conventional Commits

Формат: `<type>(<scope>): <subject>`

Типы:
- `feat` — новая функциональность
- `fix` — исправление бага
- `docs` — изменения в документации
- `style` — форматирование, точки с запятой и т.п. (без изменения логики)
- `refactor` — рефакторинг без изменения функциональности
- `perf` — улучшение производительности
- `test` — добавление/изменение тестов
- `build` — изменения в сборке/зависимостях
- `chore` — рутинные задачи (бэкапы, конфиги)
- `security` — изменения, связанные с безопасностью

Scope (опционально): `backend`, `frontend`, `ner`, `llm`, `crypto`, `ui`, `docs`, `infra`

Примеры:
```
feat(backend): add INN regex recognizer with checksum validation

Implements PatternRecognizer for Russian INN (10 and 12 digit variants)
with proper checksum validation. Adds Russian context words ("ИНН",
"ИИН") to boost detection confidence.

Closes task #2
```

```
fix(ner): handle Russian name declensions in entity matching

EntityRegistry was failing to match "Иванова" (genitive) with "Иванов"
(nominative). Added pymorphy3-based normalization before lookup.
```

```
docs(adr): add ADR-0006 on native LLM adapters
```

### После завершения задачи

```powershell
# 1. Финальные тесты и линтеры
ruff check . && ruff format --check . && mypy app && pytest

# 2. Обновить CHANGELOG.md
# Добавить запись в раздел [Unreleased]

# 3. Слияние в main
git checkout main
git merge --no-ff task/NN-short-description
git branch -d task/NN-short-description

# 4. Тег если это релиз
git tag -a v0.1.0-alpha -m "Alpha release"

# 5. Бэкап
.\scripts\backup.ps1
```

## Стандарты кода

### Python
- Python 3.12+
- Type hints обязательны для всех публичных функций
- Docstrings в стиле Google для всех публичных API
- Pydantic v2 для всех data structures, пересекающих границы модулей
- ruff (линтер) + black (форматтер), line length 100
- mypy в strict mode для `app/services/`
- pytest для тестов, минимум 70% coverage для core логики

### TypeScript
- TypeScript strict mode
- Функциональные React компоненты с хуками, никаких классов
- Все пользовательские строки через i18next, никаких хардкоженных
- Tailwind CSS 4 с CSS-переменными для тем
- ESLint + Prettier
- Vitest для тестов

Полный гайд: [`docs/CODE_STYLE.md`](docs/CODE_STYLE.md).

## Тестирование

- **Unit-тесты** для всей бизнес-логики (NER, EntityRegistry, адаптеры)
- **Integration-тесты** для FastAPI endpoints через TestClient
- **Регрессионные тесты** для NER pipeline на синтетическом корпусе
- **Метрики качества анонимизации**: precision и recall на synthetic test set
- **E2E** через Playwright (опционально для MVP)

Подробнее: [`docs/TESTING.md`](docs/TESTING.md).

## Безопасность

⚠️ **Никогда не коммитить**:
- API ключи (любые)
- Реальные клиентские документы
- Содержимое `.env`
- Mapping tables, ключи шифрования
- Дампы памяти или логи с PII

⚠️ **Никогда не логировать**:
- Оригинальный текст документов
- Содержимое EntityRegistry
- Mapping table
- Master key или сессионные ключи
- Полные ответы Cloud LLM (только анонимизированные версии)

Pre-commit hook `detect-secrets` помогает ловить утечки секретов перед коммитом.

Подробнее: [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md), [`SECURITY.md`](SECURITY.md).

## Документация

Любое значимое архитектурное решение фиксируется в ADR. Новые ADR создаются по шаблону `docs/adr/README.md` с инкрементальной нумерацией.

Изменения публичного API документируются в `docs/API.md` и в коммите с типом `docs`.

Все изменения, видимые пользователю, фиксируются в `CHANGELOG.md` в разделе `[Unreleased]`.

## Бэкапы

Перед каждой серьёзной задачей и в конце каждого рабочего дня:
```powershell
.\scripts\backup.ps1 -Destination "D:\Backups\CLEARGATE"
```

Скрипт делает git bundle, архивирует рабочую директорию (исключая модели и venv), шифрует, ротирует по GFS-схеме. Подробнее: [`docs/BACKUP.md`](docs/BACKUP.md).

## Вопросы

Поскольку проект разрабатывается одним человеком, все вопросы решаются непосредственно в диалоге с Claude Code или фиксируются в `docs/PROMPT_LIBRARY.md` для повторного использования.
