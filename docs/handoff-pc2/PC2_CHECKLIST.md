# PC #2 — pre-flight checklist

Прежде чем открывать новый чат на ПК #2 — пробежись по списку. Минут 10 максимум.

## 1. Системные тулы (большинство уже стоит)

- [ ] **Docker Desktop** — иконка кита в трее зелёная (запустить, дождаться полной загрузки)
- [ ] **Ollama** — `curl http://localhost:11434/api/tags` возвращает JSON
- [ ] **Git** — `git --version` работает в PowerShell
- [ ] **Python 3.11+** — `python --version` работает
- [ ] **Node.js 18+** — `node --version` (опционально, нужно если будем создавать docx)

## 2. Models в Ollama

```powershell
ollama list
```

Должны быть (или скачаются автоматом при запуске `bench-models.bat`):
- [ ] `qwen2.5:7b-instruct-q4_K_M` — основная модель пилота, ~4.7 GB
- [ ] `gemma4:26b` — Gemma 4 26B MoE для сравнения, ~18 GB (на RTX 3090 24GB влезет с запасом)
- [ ] (опционально для тройного сравнения) `gemma4:e4b` (~9.6 GB, ближе по размеру к Qwen 7B) или `gemma4:e2b` (~7.2 GB, малая)

Если каких-то нет — скрипт `bench-models.bat` сам делает `ollama pull`.

## 3. Cleargate репозиторий

```powershell
# Если репо ещё не клонирован:
cd C:\Users\V\Documents\Claude\Projects
git clone https://github.com/vokgpt-cyber/ClearGate.git Velum
cd Velum

# Если уже есть — обновить:
cd C:\Users\V\Documents\Claude\Projects\Velum
git pull
```

- [ ] Папка существует: `C:\Users\V\Documents\Claude\Projects\Velum`
- [ ] Свежий код: `git log --oneline -3` показывает `feat(bench)` и `feat(local)`

## 4. Handoff bundle на месте

- [ ] Папка существует: `C:\Users\V\Documents\Cleargate-Handoff\`
- [ ] Содержит:
  - [ ] `HANDOFF_BRIEF.md`
  - [ ] `PC2_CHECKLIST.md` (этот файл)
  - [ ] `VERSION_INFO.txt`
  - [ ] `memory\` с ~35 .md файлами

Если нет — скопируй с ПК #1 (USB / OneDrive / Yandex Disk).

## 5. Claude Desktop настроен

- [ ] Установлен и обновлён до актуальной версии
- [ ] **Залогинен под `vokgpt@gmail.com`** (тот же что на ноуте — критично!)
- [ ] Подключены workspace folders (Cowork → Folders → Add):
  - [ ] `C:\Users\V\Documents\Claude\Projects\Velum`
  - [ ] `C:\Users\V\Documents\Claude\Projects\Velum\frontend`
- [ ] В проекте Velum в настройках вписан project instructions (текст в `HANDOFF_BRIEF.md` секция 5)
- [ ] Установлены skill-плагины (список в `HANDOFF_BRIEF.md` секция 5):
  - [ ] anthropic-skills
  - [ ] design
  - [ ] cowork-plugin-management

## 6. Quick smoke test (рекомендуется)

Перед открытием чата — убедиться что локальный Cleargate стартует:

```powershell
cd C:\Users\V\Documents\Claude\Projects\Velum
.\scripts\start-local.bat
# Браузер откроется на http://localhost
# Залогиниться admin/admin
# Загрузить любой test\01_NDA.docx
# Убедиться что анонимизация работает (модель — что попадётся первой)
.\scripts\stop-local.bat
```

Если всё зелёное — можно открывать чат.

## 7. Открываем новый чат

- [ ] В Claude Desktop переключиться на проект **Velum**
- [ ] Создать новый чат
- [ ] Скопировать текст bootstrap-message из `HANDOFF_BRIEF.md` секция 7
- [ ] Вставить и отправить
- [ ] Дождаться пока я подгружу memory, обновлю user_role.md под новое железо, и скажу «готов, следующий шаг — запустить bench-models.bat»

## 8. После того как чат стартовал

Запустить полное сравнение моделей:
```powershell
cd C:\Users\V\Documents\Claude\Projects\Velum
$env:MODELS = "qwen2.5:7b-instruct-q4_K_M gemma4:26b"
.\scripts\bench-models.bat
```

Подождать 30-60 минут (зависит от того скачаны ли модели). Прислать мне `bench-results/comparison-*.md` — будем разбирать.

---

## Если на каком-то шаге не работает

**Docker Desktop не стартует:** перезапустить через диспетчер задач, проверить что WSL2 включён.

**Ollama не отвечает на 11434:** запустить через приложение Ollama в трее, или `ollama serve` в отдельном PowerShell.

**git clone спрашивает credentials:** Windows Git Credential Manager откроет браузер, ты подтвердишь свою сессию vokgpt-cyber на github.com (один раз).

**Claude Desktop не видит plugins:** перезагрузить приложение (полностью, через трей), проверить что синхронизация с аккаунтом завершилась.

**Workspace folder подключается, но CLAUDE.md не загружается:** убедиться что в корне проекта есть файл, и в Cowork выбрана именно эта папка как workspace, не родительская.

**Memory копирование вручную (если автоматическое не сработает):** см. `HANDOFF_BRIEF.md` секция 7 — там описано как я подцеплю файлы из `Cleargate-Handoff\memory\` и сам скопирую в реальный auto-memory dir.
