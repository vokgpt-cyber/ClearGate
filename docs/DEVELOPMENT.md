# Development Environment Setup — Windows 11

Полная инструкция по подготовке dev окружения для VELUM на Windows 11. Все шаги протестированы на чистой системе.

## Аппаратные требования (Alpha)

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| CPU | 8 ядер | AMD Ryzen 9 / Intel i7+ |
| RAM | 16 ГБ | 32 ГБ |
| GPU | RTX 4060 (8 ГБ VRAM) | RTX 4070+ |
| Диск | 100 ГБ SSD | 500 ГБ NVMe SSD |
| ОС | Windows 11 22H2+ | Windows 11 23H2+ |

## Установка зависимостей

### 1. Базовые инструменты

```powershell
# Запустить PowerShell от администратора
# Установка через winget:

winget install Git.Git
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Microsoft.VisualStudioCode
winget install Rustlang.Rustup
winget install Ollama.Ollama
winget install 7zip.7zip
```

После установки **перезапусти терминал**, чтобы PATH обновился.

### 2. Docker Desktop

```powershell
winget install Docker.DockerDesktop
```

После установки:
1. Запустить Docker Desktop
2. Settings → Resources → WSL Integration → включить
3. Settings → Resources → GPU → включить (если есть NVIDIA GPU)

### 3. NVIDIA GPU support

```powershell
# Установить последние NVIDIA драйверы вручную:
# https://www.nvidia.com/Download/index.aspx

# Проверить:
nvidia-smi

# Должно показать карточку и версию CUDA
```

Для Docker GPU:
```powershell
# Уже включается через Docker Desktop GUI
# Проверка:
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

### 4. Tauri prerequisites

```powershell
# WebView2 (обычно уже установлен на Windows 11)
winget install Microsoft.EdgeWebView2Runtime

# Visual Studio Build Tools (нужны для Rust на Windows)
winget install Microsoft.VisualStudio.2022.BuildTools --silent --override "--wait --quiet --add ProductLang En-us --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

# Tauri CLI
cargo install tauri-cli --version "^2.0.0"
```

### 5. PowerShell 7+ (рекомендуется)

```powershell
winget install Microsoft.PowerShell
```

После установки используй `pwsh.exe` вместо `powershell.exe`.

## Клонирование / распаковка проекта

### Если есть архив
```powershell
# Распаковать
cd D:\Projects
Expand-Archive velum.zip -DestinationPath .
cd velum

# Инициализировать git
git init -b main
git add .
git commit -m "Initial import from package"
```

### Если есть git bundle
```powershell
git clone D:\Backups\VELUM\daily\velum_2026-04-09.bundle D:\Projects\velum
cd D:\Projects\velum
```

## Setup проекта

### Автоматический setup
```powershell
cd D:\Projects\velum
.\scripts\setup-dev.ps1
```

Скрипт сам:
- Проверит prerequisites
- Создаст Python venv
- Установит зависимости backend
- Установит зависимости frontend
- Настроит pre-commit hooks
- Создаст .env из .env.example
- Сгенерирует VELUM_MASTER_KEY

### Ручной setup (если автоматический не сработал)

```powershell
# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

# Frontend
cd ..\frontend
npm install
cargo install tauri-cli  # один раз глобально

# Pre-commit
cd ..
pip install pre-commit
pre-commit install
```

## Настройка .env

```powershell
copy .env.example .env
notepad .env
```

Заполнить как минимум:
- `ANTHROPIC_API_KEY` — получить на https://console.anthropic.com
- `OPENAI_API_KEY` — получить на https://platform.openai.com
- `GOOGLE_API_KEY` — получить на https://aistudio.google.com
- `VELUM_MASTER_KEY` — сгенерируется автоматически через setup-dev.ps1

## Загрузка ML моделей

```powershell
.\scripts\download-models.ps1 -Profile alpha
```

Скрипт скачает:
- spaCy ru_core_news_lg (~540 МБ)
- GLiNER medium-v2.1 (~440 МБ)
- Qwen 2.5 7B Q4_K_M через Ollama (~4.8 ГБ)

Итого ~6 ГБ на диске + ~6 ГБ VRAM при работе.

## Запуск проекта

### Через Docker (проще)
```powershell
docker compose up -d
docker compose logs -f backend
```

### Нативно (быстрее для разработки)
```powershell
# Терминал 1: Ollama
ollama serve

# Терминал 2: Backend
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# Терминал 3: Frontend
cd frontend
npm run tauri dev
```

Приложение откроется в Tauri-окне.

## Конфигурация VS Code

### Recommended extensions
```json
// .vscode/extensions.json
{
  "recommendations": [
    "anthropic.claude-code",
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff",
    "tamasfe.even-better-toml",
    "rust-lang.rust-analyzer",
    "tauri-apps.tauri-vscode",
    "dbaeumer.vscode-eslint",
    "esbenp.prettier-vscode",
    "bradlc.vscode-tailwindcss",
    "ms-azuretools.vscode-docker",
    "eamodio.gitlens"
  ]
}
```

### Settings
```json
// .vscode/settings.json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/backend/.venv/Scripts/python.exe",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["backend/tests"],
  "[python]": {
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    },
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "[typescript]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[typescriptreact]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "tailwindCSS.experimental.classRegex": [
    ["clsx\\(([^)]*)\\)", "(?:'|\"|`)([^']*)(?:'|\"|`)"]
  ],
  "files.exclude": {
    "**/__pycache__": true,
    "**/.pytest_cache": true,
    "**/.mypy_cache": true,
    "**/.ruff_cache": true,
    "**/node_modules": true,
    "**/.venv": true,
    "**/target": true
  }
}
```

## Проверка установки

```powershell
# Backend health check
curl http://localhost:8000/health
# Должно вернуть: {"status":"ok","version":"0.1.0-alpha","profile":"alpha"}

# Backend OpenAPI docs
start http://localhost:8000/docs

# Tests
cd backend
pytest -v --tb=short

# Linters
ruff check .
mypy app

# Frontend tests
cd ..\frontend
npm test
npm run lint
```

## Решение проблем

### "Python is not recognized"
PATH не обновился после установки. Перезапусти PowerShell.

### "torch not found" при загрузке моделей
```powershell
.\.venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

### Ollama не запускается на GPU
```powershell
# Проверить, что NVIDIA драйвер видит карту:
nvidia-smi

# Запустить Ollama явно с GPU:
$env:OLLAMA_USE_CUDA = "1"
ollama serve
```

### "VELUM_MASTER_KEY not set"
```powershell
# Сгенерировать новый ключ
$key = python -c "import secrets; print(secrets.token_urlsafe(32))"
Add-Content .env "VELUM_MASTER_KEY=$key"
```

### Tauri build падает с ошибкой "link.exe not found"
Не установлены VS Build Tools. Запусти:
```powershell
winget install Microsoft.VisualStudio.2022.BuildTools --silent --override "--wait --quiet --add ProductLang En-us --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

### Pre-commit падает с "command not found"
```powershell
.\backend\.venv\Scripts\activate
pip install pre-commit
pre-commit install
```

### Docker build падает на NER pipeline
Убедись, что у Docker есть GPU access (Settings → Resources → GPU). Перезапусти Docker Desktop.

## Дальнейшие шаги

После успешной установки:

1. Прочитай `CLAUDE.md` (главный файл для Claude Code)
2. Прочитай `docs/ARCHITECTURE.md`
3. Открой Claude Code в VS Code
4. Запусти первую задачу: `/run-task 01` (или вручную через `docs/tasks/01-project-init.md`)
