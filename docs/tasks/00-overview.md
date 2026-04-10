# Tasks Overview — VELUM MVP Development

Этот каталог содержит **task files** для разработки VELUM через Claude Code. Каждая задача — это самодостаточный документ с контекстом, требованиями, файлами и acceptance criteria, которого достаточно, чтобы Claude Code мог выполнить её без дополнительных вопросов.

## Как работать с задачами

### 1. Подготовка
Перед началом задачи:
```powershell
# Бэкап
.\scripts\backup.ps1

# Убедись что main чистый
git status
git checkout main

# Создай ветку
git checkout -b task/NN-short-description
```

### 2. Запуск задачи в Claude Code
В Claude Code открой проект и скажи:
```
Прочитай docs/tasks/NN-task-name.md и выполни задачу полностью.
Перед началом изучи CLAUDE.md и связанные ADR.
После завершения покажи мне diff изменений и список новых файлов.
```

### 3. Ревью и коммит
- Проверь все acceptance criteria из задачи
- Запусти тесты: `pytest` (backend) или `npm test` (frontend)
- Запусти линтеры: `ruff check . && mypy app`
- Коммит с Conventional Commits format
- Обнови `CHANGELOG.md`

### 4. Слияние и бэкап
```powershell
git checkout main
git merge --no-ff task/NN-short-description
git branch -d task/NN-short-description
.\scripts\backup.ps1
```

## Список задач MVP

| № | Задача | Зависимости | Файл |
|---|--------|-------------|------|
| 01 | Project initialization | — | [01-project-init.md](01-project-init.md) |
| 02 | Russian PII regex recognizers | 01 | [02-regex-recognizers.md](02-regex-recognizers.md) |
| 03 | NER pipeline (Presidio + spaCy + GLiNER) | 02 | [03-ner-pipeline.md](03-ner-pipeline.md) |
| 04 | EntityRegistry с шифрованием | 02 | [04-entity-registry.md](04-entity-registry.md) |
| 05 | SplitScreen UI компонент | 01 | [05-split-screen-component.md](05-split-screen-component.md) |
| 06 | API routes для анонимизации | 03, 04 | [06-anonymize-api-routes.md](06-anonymize-api-routes.md) |
| 07 | Claude LLM adapter | 01 | [07-claude-llm-adapter.md](07-claude-llm-adapter.md) |
| 08 | WebSocket streaming | 06, 07 | [08-websocket-streaming.md](08-websocket-streaming.md) |
| 09 | LLM Panel UI компонент | 05 | [09-llm-panel-component.md](09-llm-panel-component.md) |
| 10 | Theme и i18n (RU/EN, light/dark) | 05 | [10-theme-and-i18n.md](10-theme-and-i18n.md) |

## Общие принципы для всех задач

**Что Claude Code должен делать в каждой задаче:**

1. **Прочитать** релевантные ADR перед началом (указано в каждой задаче)
2. **Создать тесты** для всей новой логики (минимум happy path + 1-2 edge case)
3. **Написать docstrings** для всех публичных функций (Google style для Python, JSDoc для TS)
4. **Использовать type hints** везде (mypy strict mode для Python, TS strict mode)
5. **Локализовать** все пользовательские строки через i18next (никаких хардкоженных RU/EN в JSX)
6. **Не логировать** оригинальный текст, mapping table, ключи

**Что Claude Code НЕ должен делать:**

1. Удалять файлы без явного разрешения
2. Менять архитектурные решения, зафиксированные в ADR (если кажется, что нужно — сначала обсудить)
3. Добавлять зависимости, не указанные в задаче (если что-то нужно — спросить)
4. Использовать unified LLM shim'ы (LiteLLM и т.п.) — только нативные SDK
5. Коммитить .env, реальные данные, mapping tables

## Формат каждого task file

```markdown
# Task NN: Title

## Контекст
Зачем эта задача нужна, какое место занимает в архитектуре

## Зависимости
- Какие задачи должны быть выполнены до этой
- Какие ADR прочитать

## Цель
Что должно быть на выходе

## Требования
Конкретный список того, что нужно реализовать

## Файлы для создания/изменения
Точные пути

## Реализация
Псевдокод / структура / примеры

## Тесты
Какие тесты должны быть написаны

## Acceptance Criteria
Чек-лист для проверки готовности

## Команды для запуска
Как запустить и протестировать локально
```
