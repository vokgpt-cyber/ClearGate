# Task 01: Project Initialization

## Контекст

Это первая задача — создать базовый скелет проекта VELUM: структуру папок, конфиги Tauri+Next.js+FastAPI, Docker Compose, git инициализацию, базовые тесты-заглушки. Цель — получить рабочее окружение, в котором можно запустить пустой Tauri-app, обратиться к FastAPI бэкенду на `/health` и получить ответ.

## Зависимости

- Прочитать `CLAUDE.md` (root)
- Прочитать `docs/ARCHITECTURE.md` (раздел 2 — Компоненты системы)
- Прочитать `docs/adr/0001-use-tauri-over-electron.md`

## Цель

После выполнения должно работать:
```powershell
# Backend
cd backend && uvicorn app.main:app --reload
# → http://localhost:8000/health возвращает {"status": "ok", "version": "0.1.0-alpha"}

# Frontend
cd frontend && npm run tauri dev
# → Tauri окно открывается, показывает страницу с надписью "VELUM" и статусом подключения к backend
```

## Требования

### Backend (Python/FastAPI)
1. Создать структуру `backend/`:
   ```
   backend/
   ├── app/
   │   ├── __init__.py
   │   ├── main.py
   │   ├── config.py
   │   ├── routers/
   │   │   ├── __init__.py
   │   │   └── health.py
   │   ├── services/
   │   │   └── __init__.py
   │   └── models/
   │       └── __init__.py
   ├── tests/
   │   ├── __init__.py
   │   └── test_health.py
   ├── pyproject.toml      # копия root pyproject.toml для backend
   └── README.md
   ```

2. `app/main.py`:
   - FastAPI app с lifespan handler
   - CORS middleware (origins из env)
   - Подключение router'а health
   - Метаданные: title="VELUM Backend", version из config

3. `app/config.py`:
   - Pydantic Settings класс
   - Загрузка из .env
   - Поля: VELUM_PROFILE, BACKEND_HOST, BACKEND_PORT, BACKEND_CORS_ORIGINS, версия

4. `app/routers/health.py`:
   - GET `/health` — возвращает `{status, version, profile, timestamp}`
   - GET `/health/ready` — заготовка под readiness check (проверка моделей загружены)

5. `tests/test_health.py`:
   - Тест GET /health возвращает 200 и правильную структуру
   - Использовать FastAPI TestClient

### Frontend (Tauri + Next.js)
1. Создать структуру `frontend/`:
   ```
   frontend/
   ├── src-tauri/
   │   ├── src/main.rs
   │   ├── Cargo.toml
   │   ├── tauri.conf.json
   │   └── icons/
   ├── src/
   │   ├── app/
   │   │   ├── layout.tsx
   │   │   ├── page.tsx
   │   │   └── globals.css
   │   ├── components/
   │   └── lib/
   ├── public/
   ├── next.config.js
   ├── tsconfig.json
   ├── tailwind.config.ts
   ├── postcss.config.js
   ├── package.json
   └── README.md
   ```

2. `next.config.js`: статический экспорт (`output: 'export'`), `images.unoptimized: true`

3. `src-tauri/tauri.conf.json`:
   - Window: 1400x900, resizable, title "VELUM"
   - Build commands: `npm run build` → `npm run dev`
   - Capability config: пока разрешить только http запросы к localhost:8000

4. `src/app/page.tsx`: простой компонент с заголовком "VELUM" и состоянием подключения к backend (fetch /health, показ статуса)

5. `package.json` scripts:
   - `dev`, `build`, `start`, `lint`, `format`, `test`
   - `tauri:dev`, `tauri:build`

### Root level
1. `docker-compose.yml` — Alpha конфигурация:
   - Service `backend` (build из `./backend`)
   - Service `frontend` (build из `./frontend`)  
   - Service `ollama` (image `ollama/ollama:latest`)
   - GPU runtime для backend и ollama
   - Networks: внутренняя `velum-net`
   - Volumes для моделей

2. `.pre-commit-config.yaml` (см. Task 10 для финальной версии, базовый сейчас):
   - ruff
   - black
   - detect-secrets
   - trailing-whitespace
   - end-of-file-fixer

3. Создать пустые папки `models/`, `logs/`, `backups/` с `.gitkeep` (но добавить в gitignore чтобы содержимое не коммитилось)

## Файлы для создания

См. раздел "Требования" — каждый указанный путь.

## Тесты

```powershell
cd backend
pytest tests/test_health.py -v
# Должно пройти 1 тест минимум
```

## Acceptance Criteria

- [ ] `git status` после инициализации показывает чистое состояние с правильным .gitignore (никаких node_modules, .venv, __pycache__)
- [ ] `cd backend && uvicorn app.main:app --reload` запускается без ошибок
- [ ] `curl http://localhost:8000/health` возвращает JSON со статусом ok
- [ ] `pytest backend/tests/` проходит
- [ ] `cd frontend && npm install && npm run tauri dev` открывает окно Tauri
- [ ] В окне Tauri виден заголовок VELUM и статус подключения к backend (зелёный, если backend запущен)
- [ ] `docker compose config` валидирует docker-compose.yml без ошибок
- [ ] Pre-commit hooks установлены и работают (`pre-commit run --all-files`)

## Команды для запуска

```powershell
# Установка зависимостей
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"

cd ..\frontend
npm install
cargo install tauri-cli  # один раз глобально

# Pre-commit
cd ..
pre-commit install

# Запуск
cd backend && uvicorn app.main:app --reload
# в другом терминале:
cd frontend && npm run tauri dev
```

## После завершения

```powershell
git add .
git commit -m "feat: initialize VELUM project structure

- Backend: FastAPI skeleton with health endpoint
- Frontend: Tauri 2 + Next.js 15 with Russian/English ready
- Docker Compose for Alpha profile
- Pre-commit hooks for ruff, black, detect-secrets

Closes task #1"

# Обновить CHANGELOG.md в разделе [Unreleased]

# Бэкап
.\scripts\backup.ps1
```
