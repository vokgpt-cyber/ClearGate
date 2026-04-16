# Git Workflow — Solo Developer Edition

## Контекст

CLEARGATE разрабатывается **одним человеком** на **локальном git репозитории** (без GitHub/GitLab). Это меняет некоторые best practices: PR-флоу не нужен, code review делает Claude Code на лету, защита от concurrent коммитов не требуется. Но дисциплина веток, истории и коммитов всё равно важна — для возможности откатиться, для чтения истории через год, для будущего масштабирования на команду.

## Branching strategy: Trunk-based с feature branches

```
main ────●────●────●────●────●─── (всегда зелёный)
          \       /     \    /
           ●─●─●─●       ●●●
        task/02-regex   task/03-ner
```

- **`main`** — всегда работоспособное состояние, всегда проходит тесты
- **`task/NN-short-name`** — feature branch на одну задачу из `docs/tasks/`
- После завершения задачи — merge в main с `--no-ff` (явный merge commit)
- После merge ветка удаляется

### Почему не GitFlow

GitFlow с `develop`, `release`, `hotfix` ветками — overkill для одного разработчика. Trunk-based проще, понятнее и не создаёт ложного ощущения процесса.

### Почему feature branches, а не прямо в main

- Возможность откатить целую задачу одним `git reset`
- Чистая история через `--no-ff` merge commits
- Видно, какие изменения относились к какой задаче
- Если задача не получилась — branch удаляется без следа в main

## Жизненный цикл задачи

```powershell
# 1. Бэкап текущего состояния
.\scripts\backup.ps1

# 2. Проверка, что main чистый
git status                    # должно быть "nothing to commit"
git checkout main

# 3. Создать feature branch
git checkout -b task/02-regex-recognizers

# 4. Работа с Claude Code
# ... много мелких коммитов в процессе ...
git add backend/app/services/checksum_validators.py
git commit -m "feat(backend): add INN checksum validators"

git add backend/app/services/regex_recognizers.py
git commit -m "feat(backend): add InnRecognizer for Presidio"

git add backend/tests/services/test_checksum_validators.py
git commit -m "test(backend): add INN validator tests"

# 5. Финальные проверки
cd backend
pytest tests/services/ -v
ruff check app/
mypy app/

# 6. Обновить CHANGELOG.md
# Добавить запись в [Unreleased] / Added

# 7. Финальный коммит с CHANGELOG
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for task 02"

# 8. Merge в main
git checkout main
git merge --no-ff task/02-regex-recognizers -m "Merge task/02: Russian PII regex recognizers

Implements 9 PatternRecognizer classes for Russian PII with full
checksum validation. 90% test coverage. Closes task #2."

# 9. Удалить ветку
git branch -d task/02-regex-recognizers

# 10. Тег если это значимая веха
# (для крупных задач, не для каждой)
git tag -a v0.1.0-alpha.2 -m "Russian regex recognizers complete"

# 11. Финальный бэкап
.\scripts\backup.ps1
```

## Conventional Commits

Формат: `<type>(<scope>): <subject>`

### Типы

| Type | Когда использовать | Пример |
|------|--------------------|--------|
| `feat` | Новая функциональность | `feat(backend): add Claude LLM adapter` |
| `fix` | Исправление бага | `fix(ner): handle Russian declensions` |
| `docs` | Изменения в документации | `docs: update ARCHITECTURE.md` |
| `refactor` | Рефакторинг без изменения функциональности | `refactor(crypto): extract key derivation` |
| `perf` | Улучшение производительности | `perf(ner): cache normalized forms` |
| `test` | Добавление/изменение тестов | `test(entity): add fuzzy match cases` |
| `build` | Изменения в сборке/зависимостях | `build: bump anthropic to 0.41.0` |
| `chore` | Рутинные задачи | `chore: update .gitignore` |
| `style` | Форматирование, без изменения логики | `style: run ruff format` |
| `security` | Изменения безопасности | `security: rotate master key derivation` |

### Scopes

- `backend` — Python/FastAPI код
- `frontend` — TypeScript/React код
- `ner` — NER pipeline
- `llm` — LLM адаптеры
- `crypto` — шифрование
- `ui` — UI компоненты
- `docs` — документация
- `infra` — Docker, CI, инфраструктура
- `i18n` — локализация
- `theme` — темизация

### Примеры хороших коммитов

```
feat(ner): implement three-layer pipeline orchestration

NERPipeline now coordinates regex, spaCy, GLiNER and LLM layers.
Layers can be enabled/disabled independently for testing and
degraded modes. Added merging logic for overlapping spans
based on score and source layer priority.

Closes task #3
```

```
fix(crypto): use 12-byte nonce for AES-GCM as per NIST SP 800-38D

Previous implementation used a 16-byte IV which is incorrect for
GCM mode. Updated to 12-byte (96-bit) nonce as required by the
standard. Existing encrypted blobs are NOT compatible — added
migration path in docs/MIGRATIONS.md.

BREAKING CHANGE: encrypted blobs from v0.1.0-alpha.1 cannot be
decrypted with this version.
```

### Примеры плохих коммитов

```
fixed stuff                          # ❌ что именно?
update                               # ❌ что обновили?
WIP                                  # ❌ не коммить WIP в main
asdfasdf                             # ❌ no comment
fix bug                              # ❌ какой баг?
```

## Тегирование и версии

CLEARGATE использует [Semantic Versioning](https://semver.org/lang/ru/):

```
v<MAJOR>.<MINOR>.<PATCH>[-<pre-release>]
```

| Часть | Когда инкрементить |
|-------|--------------------|
| MAJOR | Breaking changes API |
| MINOR | Новые фичи без breaking changes |
| PATCH | Багфиксы |
| pre-release | `alpha`, `beta`, `rc.1` |

### Текущая roadmap версий

| Версия | Веха |
|--------|------|
| `v0.1.0-alpha` | Базовый pipeline + UI на ноутбуке |
| `v0.2.0-beta` | MVP на RTX 3090 + все три LLM провайдера |
| `v1.0.0` | Final, продакшн на серверах ЕПАМ |

### Создание тега
```powershell
git tag -a v0.1.0-alpha -m "Alpha release: working pipeline on RTX 4060"

# Посмотреть теги
git tag --list

# Информация о теге
git show v0.1.0-alpha
```

## .gitignore стратегия

Что **никогда** не коммитится:
- Секреты: `.env`, `*.key`, `*.pem`, API keys
- ML модели: `*.gguf`, `*.safetensors`, `models/`
- Зависимости: `node_modules/`, `.venv/`, `target/`
- Артефакты: `.next/`, `dist/`, `build/`, `__pycache__/`
- Реальные клиентские данные: `client_data/`, `*.real.docx`
- Mapping tables: `*.mapping`, `*.session`
- Логи: `*.log`, `logs/`
- IDE файлы: `.vscode/` (с исключениями для общих настроек), `.idea/`
- OS файлы: `.DS_Store`, `Thumbs.db`

Полный список: `.gitignore`

## Git hooks

### Pre-commit (через `pre-commit` framework)
- ruff (linter + formatter)
- black
- mypy
- detect-secrets
- gitleaks
- CLEARGATE-specific: no-pii-in-logs, no-hardcoded-strings, no-unified-shim

Конфигурация: `.pre-commit-config.yaml`

Установка: `pre-commit install`

### Pre-push hook (опционально)
Можно добавить запуск тестов перед push в main, но при локальном git это менее актуально.

## Откаты и исправления

### Отменить незакоммиченные изменения
```powershell
git checkout -- path/to/file       # один файл
git reset --hard HEAD              # все unstaged изменения
git clean -fd                      # удалить untracked файлы
```

### Изменить последний коммит (до push, до merge)
```powershell
git commit --amend                  # изменить сообщение
git add forgotten-file
git commit --amend --no-edit       # добавить файлы в последний коммит
```

### Откатить коммит, сохранив изменения
```powershell
git reset --soft HEAD~1            # коммит отменён, изменения в staging
git reset HEAD~1                   # коммит отменён, изменения в working dir
```

### Откатить коммит полностью (опасно если уже merge)
```powershell
git reset --hard HEAD~1            # все изменения теряются (есть в reflog 90 дней)
```

### Найти потерянный коммит
```powershell
git reflog                          # покажет все HEAD изменения
git checkout <hash>                 # восстановить
```

## Git aliases (рекомендуемые)

Добавь в `~/.gitconfig` или `.git/config`:

```ini
[alias]
    st = status -s
    co = checkout
    br = branch
    ci = commit
    last = log -1 HEAD
    visual = !gitk
    lg = log --color --graph --pretty=format:'%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' --abbrev-commit
    today = log --since=midnight --oneline
    week = log --since='1 week ago' --oneline
    untrack = rm --cached
```

## Финальные правила

1. **Никогда не коммить в main напрямую** — всегда через feature branch
2. **Никогда не делать `git push --force`** — для локального git это не критично, но привычка правильная
3. **Всегда бэкапить перед `git reset --hard`**
4. **Всегда читать `git status` перед `git add .`** — чтобы случайно не закоммитить .env
5. **Никогда не коммить секреты** — pre-commit hooks ловят это, но привычка важнее
6. **Атомарные коммиты** — один коммит = одно логическое изменение
7. **Понятные сообщения** — представь, что читаешь свой коммит через год
