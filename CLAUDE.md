# CLAUDE.md — VELUM

Этот файл — основная инструкция для Claude Code при работе с проектом VELUM. Прочитай его перед началом любой задачи.

## Что такое VELUM

VELUM — on-premise приложение для юристов Адвокатского бюро ЕПАМ, которое автоматически анонимизирует чувствительные данные перед отправкой в облачные LLM (Claude, GPT, Gemini) и автоматически деанонимизирует ответы. Цель — дать юристам полную мощь топовых LLM мира без риска утечки клиентских данных и нарушения адвокатской тайны.

VELUM — четвёртое приложение в экосистеме ЕПАМ:
- **VERITAS** — транскрибация и саммаризация аудио
- **EPAMOS** — CRM, биллинг, работа с клиентами
- **CONCLAVE** — видеозвонки (аналог Zoom)
- **VELUM** — анонимизация → LLM → деанонимизация (этот проект)

Подробная концепция: см. `docs/ARCHITECTURE.md` и `docs/ROADMAP.md`.

## Архитектурный обзор (1 минута чтения)

VELUM — это desktop-приложение на Tauri 2 с React/Next.js фронтендом и Python/FastAPI бэкендом. Бэкенд содержит трёхслойный pipeline анонимизации:

1. **Regex-уровень** (Microsoft Presidio PatternRecognizer) — структурированные данные: ИНН, ОГРН, СНИЛС, паспорта РФ, банковские счета, телефоны, email
2. **NER-уровень** (spaCy ru_core_news_lg + GLiNER) — неструктурированные сущности: ФИО, организации, адреса, должности
3. **LLM-уровень** (Ollama + Qwen 2.5) — сложные случаи: кореференция, составные сущности, контекстная верификация

Между уровнями работает **EntityRegistry** — реестр сущностей с консистентным маппингом «реальное значение ↔ плейсхолдер `[ЛИЦО_1]`», нормализацией русских имён через pymorphy3 и AES-256-GCM шифрованием mapping table в памяти.

После анонимизации текст уходит через нативные адаптеры (НЕ unified shim) в Claude/GPT/Gemini, ответ деанонимизируется обратной заменой по EntityRegistry и показывается юристу с diff-подсветкой изменений.

## Структура проекта

```
velum/
├── CLAUDE.md                    ← ты здесь
├── README.md
├── backend/                     ← Python FastAPI + ML pipeline
│   ├── CLAUDE.md                ← инструкции специально для backend работ
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/             ← FastAPI endpoints
│   │   ├── services/            ← бизнес-логика (NER, EntityRegistry, LLM adapters)
│   │   ├── models/              ← Pydantic schemas
│   │   └── config.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/                    ← Tauri + React + Next.js
│   ├── CLAUDE.md                ← инструкции специально для frontend работ
│   ├── src-tauri/               ← Rust shell
│   └── src/                     ← React приложение
├── docs/
│   ├── ARCHITECTURE.md          ← подробная архитектура
│   ├── API.md                   ← спецификация REST/WebSocket API
│   ├── TESTING.md
│   ├── DEPLOYMENT.md
│   ├── DEVELOPMENT.md           ← как поднять dev окружение на Windows 11
│   ├── BACKUP.md                ← стратегия бэкапов
│   ├── GIT_WORKFLOW.md
│   ├── CODE_STYLE.md
│   ├── SECURITY_MODEL.md
│   ├── ROADMAP.md
│   ├── PROMPT_LIBRARY.md
│   ├── adr/                     ← Architecture Decision Records
│   └── tasks/                   ← задачи для Claude Code (ниже)
├── scripts/
│   ├── backup.ps1               ← бэкап с GFS-ротацией
│   ├── setup-dev.ps1
│   ├── download-models.ps1
│   └── restore-backup.ps1
├── .claude/
│   ├── settings.json
│   └── commands/                ← кастомные slash commands
├── docker-compose.yml           ← Alpha (RTX 4060)
├── docker-compose.mvp.yml       ← MVP (RTX 3090)
├── .gitignore
├── .env.example
└── pyproject.toml               ← workspace-level config
```

## Команды разработки

**Запуск dev-окружения:**
```powershell
# Backend (Python)
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# Frontend (Tauri + Next.js)
cd frontend
npm run tauri dev

# Локальная LLM
ollama serve
ollama run qwen2.5:7b-instruct-q4_K_M
```

**Тесты:**
```powershell
# Backend
cd backend && pytest -v --cov=app

# Frontend
cd frontend && npm test
```

**Линтинг и форматирование:**
```powershell
# Backend
cd backend && ruff check . && ruff format . && mypy app

# Frontend
cd frontend && npm run lint && npm run format
```

**Бэкап (запускать перед каждым серьёзным изменением):**
```powershell
.\scripts\backup.ps1 -Destination "D:\Backups\VELUM"
```

**Docker (Alpha):**
```powershell
docker compose up -d
```

## Workflow с задачами

Все крупные задачи разработки находятся в `docs/tasks/`. Каждая задача — это самодостаточный документ с контекстом, точными требованиями, файлами для создания, acceptance criteria и тестами.

**Порядок выполнения задач для MVP:**
1. `docs/tasks/01-project-init.md` — инициализация структуры
2. `docs/tasks/02-regex-recognizers.md` — российские PII regex
3. `docs/tasks/03-ner-pipeline.md` — Presidio + spaCy + GLiNER
4. `docs/tasks/04-entity-registry.md` — реестр с шифрованием
5. `docs/tasks/05-split-screen-component.md` — UI split-screen
6. `docs/tasks/06-anonymize-api-routes.md` — REST endpoints
7. `docs/tasks/07-claude-llm-adapter.md` — Anthropic adapter
8. `docs/tasks/08-websocket-streaming.md` — WS streaming
9. `docs/tasks/09-llm-panel-component.md` — UI выбора LLM
10. `docs/tasks/10-theme-and-i18n.md` — темы и локализация

**Когда берёшься за задачу:**
1. Прочитай файл задачи целиком
2. Прочитай связанные ADR в `docs/adr/`
3. Прочитай sub-CLAUDE.md (`backend/CLAUDE.md` или `frontend/CLAUDE.md`)
4. Создай ветку: `git checkout -b task/NN-short-name`
5. Реализуй
6. Запусти тесты и линтеры
7. Закоммить с Conventional Commits: `feat(backend): add INN regex recognizer`
8. Сделай бэкап: `.\scripts\backup.ps1`

## Что Claude Code ДОЛЖЕН делать

- **Всегда читать** `docs/ARCHITECTURE.md` и релевантные ADR перед началом работы
- **Следовать стилю кода**: ruff + black для Python, eslint + prettier для TypeScript (см. `docs/CODE_STYLE.md`)
- **Писать тесты** для всей бизнес-логики (NER, EntityRegistry, адаптеры LLM)
- **Использовать Conventional Commits** для каждого коммита
- **Обновлять CHANGELOG.md** после завершения значимой задачи
- **Создавать ADR** при принятии новых архитектурных решений
- **Спрашивать** перед удалением/массовым переименованием файлов
- **Бэкапить** через `scripts/backup.ps1` перед рискованными изменениями
- **Уважать privacy by design**: никогда не логировать оригинальный текст, mapping table или ключи

## Что Claude Code НЕ должен делать

- **НЕ коммитить** `.env`, `secrets/`, ключи API, маппинг-таблицы, реальные клиентские документы
- **НЕ логировать** оригинальные тексты документов, содержимое EntityRegistry, ключи шифрования
- **НЕ использовать** unified LLM shim'ы (LiteLLM и т.п.) — нужны нативные адаптеры с доступом к extended thinking каждого провайдера (см. ADR-0006)
- **НЕ загружать** модели в git (см. `.gitignore`) — модели грузятся через `scripts/download-models.ps1`
- **НЕ ломать** обратную совместимость API между версиями без соответствующей записи в CHANGELOG
- **НЕ добавлять** зависимости без обновления `pyproject.toml` / `package.json` и без обоснования в коммите
- **НЕ писать код**, который отправляет данные в облако в обход анонимизации — это фатальное нарушение модели угроз (см. `docs/SECURITY_MODEL.md`)

## Стиль кода (краткая выжимка)

**Python:**
- Python 3.12+, type hints обязательны
- ruff для линтинга, black для форматирования (line length 100)
- mypy strict mode для `app/services/`
- Docstrings в стиле Google для публичных функций
- Pydantic v2 для всех моделей данных

**TypeScript/React:**
- TypeScript strict mode
- Функциональные компоненты + хуки, никаких классов
- Tailwind CSS 4 с CSS variables для тем
- i18next для всех пользовательских строк (никаких хардкоженных русских/английских строк в JSX)
- Названия компонентов — PascalCase, файлы — kebab-case или PascalCase согласованно

Полный гайд: `docs/CODE_STYLE.md`.

## Импорты других CLAUDE.md и ключевых документов

@backend/CLAUDE.md
@frontend/CLAUDE.md
@docs/ARCHITECTURE.md
@docs/SECURITY_MODEL.md
@docs/CODE_STYLE.md
@docs/GIT_WORKFLOW.md

## Контакты и контекст

- **Разработчик:** руководитель ЕПАМ, использует вайб-кодинг через Claude Code, работает на ASUS ROG G14 (Windows 11, RTX 4060)
- **Часовой пояс:** Москва (MSK)
- **Конфигурация разработки:** Alpha (текущая) → MVP (rtx 3090, i9 14900KF, 64GB) → Final (кластер на серверах ЕПАМ)
- **Подход:** скорость и качество результата важнее бюрократии, но документация ведётся на enterprise-уровне для будущего масштабирования
