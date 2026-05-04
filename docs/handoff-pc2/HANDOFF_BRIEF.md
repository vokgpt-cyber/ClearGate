# CLEARGATE — handoff brief для переезда на ПК #2

**Подготовлено:** 30 апреля 2026, ПК #1 (ноут ASUS ROG G14, RTX 4060 8GB)
**Целевая машина:** ПК #2 (десктоп, RTX 3090 24GB, 64 GB RAM)
**Аккаунт Claude Desktop:** vokgpt@gmail.com

---

## 1. Текущий статус проекта

### Где Cleargate сейчас
- **v0.4.0-rc1 заморожена** на ветке `dev`. Теги: `v0.4.0-rc1`, `snapshot-v040-handoff-ready`. Передана айтишникам ЕПАМ для развёртывания на GPU-сервере (RTX 4090 48GB Ubuntu).
- **Пилот на CPU (v0.3.0)** продолжает работать у юристов на старом сервере — никто не трогает.
- **Phase 8 (Tauri desktop client)** перенесён в v0.4.x post-launch.

### Где основные артефакты
- Репо: `https://github.com/vokgpt-cyber/ClearGate` (ветка dev)
- IT-handoff пакет: `dist/v040/HANDOFF_README.md` + sibling-файлы
- Tarball-страховка v0.4.0: `C:\Users\V\Desktop\cleargate-v040-rc1-backup.tar.gz` (на ПК #1, переносить не обязательно)

### Что НЕЛЬЗЯ ломать без явного согласия
- `docker-compose.gpu.yml`
- `nginx.gpu.conf`
- `scripts/install-gpu.sh`
- `scripts/verify-deploy.sh`
- `docker-compose.pilot.yml` (CPU pilot стек у юристов)
- Любая правка которая ломает теги v0.4.0-rc1

`scripts/benchmark_v040.py` был расширен опцией `--tag` и расширенным discover (см. Этап 4 ниже) — это совместимое изменение, теги остаются валидны.

---

## 2. Что было сделано в последней сессии (4 этапа)

### Этап 1 — Memory & freeze documentation
Записан в memory `project_v040_rc1_frozen.md` правило «не ломать v0.4.0-rc1 без явного согласия пользователя». Добавлено в `MEMORY.md`.

### Этап 2 — Аудит папки Velum
Подготовлены команды на удаление ~11.5 GB безопасно-удаляемых артефактов (старые offline-bundles от 21-23 апреля). Реорганизация: `build_handoff_docx.py` -> `scripts/`, `CLEARGATE_Concept_v2.md` -> `docs/archive/`. Часть выполнена — проверь `git status` после pull, если что-то осталось untracked, можно закрыть отдельным маленьким коммитом.

### Этап 3 — Локальный профиль для ПК #2
Создан `docker-compose.local.yml` (минимальный compose без vLLM, без BGE, без LDAP, без TLS — использует Ollama на хосте). Скрипты: `scripts/start-local.bat`, `scripts/stop-local.bat`. Документ: `LOCAL_DEPLOY_README.md`. Идея: одна команда -> запущенный Cleargate на http://localhost с admin/admin.

### Этап 4 — Benchmark pack для сравнения моделей (только что закончили)
Создано:
- 3 новых тестовых документа: `08_pretenziya.pdf` (~2 стр), `09_protocol_sd.pdf` (~5 стр), `10_tricky_dogovor.docx` (omonyms/coreference)
- 10 файлов ground truth: `test/results/*_ground_truth.json` (455 размеченных вручную сущностей)
- Расширен `scripts/benchmark_v040.py`: discovers .docx + .pdf + .txt, prefers `*_ground_truth.json`, опция `--tag`
- Создан `scripts/compare_bench_results.py`: side-by-side Markdown отчёт для N моделей
- Создан `scripts/bench-models.bat`: one-command оркестратор (pull model -> restart backend -> benchmark -> repeat)
- Документ `test/BENCHMARK_README.md`

### Коммит-история (проверь на ПК #2 после pull)
`git log --oneline -3` должен показать топ-2 коммита:
```
feat(bench): add Qwen-vs-Gemma comparison harness and ground-truth pack
feat(local): add simple PC#2 deploy profile (host Ollama, no BGE/LDAP/TLS)
```

---

## 3. Что ПРЯМО СЕЙЧАС на повестке

**Главный вопрос:** «Qwen 2.5 7B vs Gemma 3 27B — какая модель лучше для русских юр. документов?»

**Конкретные шаги (на ПК #2):**

1. Запустить `.\scripts\start-local.bat` один раз — убедиться что Cleargate работает локально (зайти на http://localhost, залогиниться admin/admin, загрузить любой `test/*.docx`).
2. Остановить: `.\scripts\stop-local.bat`
3. Запустить полное сравнение моделей:
   ```powershell
   $env:MODELS = "qwen2.5:7b-instruct-q4_K_M gemma4:26b"
   .\scripts\bench-models.bat
   ```
4. Дождаться окончания (по 5-10 мин на модель × 2 модели + время на pull моделей при первом запуске = ~30-60 мин).
5. Прислать `bench-results/comparison-*.md` мне в новый чат — разберу результаты, дам обоснованный вердикт по выбору модели для production.

**Опционально:** для тройного сравнения добавить лёгкую Gemma 4: `gemma4:e4b` (~9.6 GB, ближе по размеру к Qwen 2.5 7B) или малую `gemma4:e2b` (~7.2 GB) — будет видно как качество масштабируется внутри семейства Gemma.

---

## 4. Hardware migration note

| | ПК #1 (старая) | ПК #2 (новая) |
|---|---|---|
| Тип | Ноут ASUS ROG G14 | Десктоп |
| GPU | RTX 4060 8GB | **RTX 3090 24GB** |
| RAM | ~32 GB | **64 GB** |
| OS | Windows 11 | Windows 11 |

В memory `user_role.md` упоминается старая dev-машина. При первом запросе на ПК #2 я предложу обновить эту memory под новые характеристики.

---

## 5. Что нужно настроить в Cowork на ПК #2

### Аккаунт
Войти под `vokgpt@gmail.com` — тот же что на ПК #1, иначе плагины не подхватятся автоматически.

### Skill-плагины (Cowork -> Plugins)
Установить те же что на ПК #1:
- **anthropic-skills** (включает: docx, pdf, pptx, xlsx, schedule, setup-cowork, skill-creator, consolidate-memory)
- **design** (8 design-skills: design-handoff, design-system, design-critique, ux-copy, research-synthesis, accessibility-review, user-research)
- **cowork-plugin-management** (cowork-plugin-customizer, create-cowork-plugin)

### Workspace folders (Cowork -> Folders -> Add)
- `C:\Users\V\Documents\Claude\Projects\Velum`
- `C:\Users\V\Documents\Claude\Projects\Velum\frontend`

### Project instructions (в настройках проекта Velum)
Скопировать ровно этот текст:
```
We are building top notch world class anonymizer app, that helps to work with legal documents in world-leading LLMs without leaking any sensitive or personal information.

Follow these instructions when working in this project.
```

### MCP-интеграции (опциональны, не критичны для Cleargate)
Gmail, Calendar, Google Drive, Slack — если используешь для других задач, подключи отдельно. Для работы над Cleargate не нужны.

---

## 6. Что в папке `memory/`

35 .md файлов — накопленный за 4+ месяца контекст. Группы:

- **Профиль пользователя** — `user_role.md`
- **Феедбэк-правила** (`feedback_*.md`) — language preference, git workflow, file tooling gotchas, UX philosophy, snapshot policy, agent destructive ops, Powershell encoding, Next.js NEXT_PUBLIC trap, и т.д.
- **Project status snapshots** (`project_*.md`) — где находится проект на каждой итерации, что сделано, что pending. Самые свежие и важные:
  - `project_v040_rc1_frozen.md` — статус v0.4.0 заморозки для IT
  - `project_pilot_deployment.md` — статус CPU-пилота у юристов
  - `project_business_process.md` — фазы 1-4 продукта
- **Reference** (`reference_*.md`) — где лежит документация, snapshot workflow, dev box traps

**Что с этим делать на ПК #2:** см. секцию 7 ниже — bootstrap message содержит инструкцию мне на чтение и копирование.

---

## 7. BOOTSTRAP MESSAGE для нового чата на ПК #2

**Это то, что ты копируешь и отправляешь первым сообщением в новый чат на ПК #2** (после того как все шаги из PC2_CHECKLIST.md пройдены).

```
Cleargate continuation — switching from the laptop (PC #1) to the desktop
(PC #2, RTX 3090 24GB, 64 GB RAM).

A handoff bundle is at: C:\Users\V\Documents\Cleargate-Handoff\

Please do this in order:

1. Read C:\Users\V\Documents\Cleargate-Handoff\memory\MEMORY.md (the index)
   and selectively read the linked files to load project context. Pay
   special attention to:
   - project_v040_rc1_frozen.md   (do NOT break the IT-handoff state!)
   - feedback_agent_destructive_ops.md   (rules for subagents)
   - feedback_language.md   (communication preference)
   - user_role.md   (then update it: I'm now on PC #2 with RTX 3090 24GB,
                     64 GB RAM, instead of the laptop with RTX 4060 8GB)

2. Read C:\Users\V\Documents\Cleargate-Handoff\HANDOFF_BRIEF.md for full
   session context — what we did last, what is pending right now.

3. Copy all .md files from C:\Users\V\Documents\Cleargate-Handoff\memory\
   into your actual auto-memory directory (the path is in your system
   prompt under "auto memory"). Verify the file count matches (~35 files).
   This persists context for future chats too.

4. Tell me you're ready and what the next concrete step is. The pending
   task right now is to run scripts\bench-models.bat in the Velum repo
   (cloned at C:\Users\V\Documents\Claude\Projects\Velum) to compare
   Qwen 2.5 7B vs Gemma 3 27B on Russian legal docs, then analyze the
   bench-results/comparison-*.md output together.
```

---

## 8. Если что-то пошло не так

**Memory не нашлась:** на ПК #1 (а не ПК #2!) посмотри пути:
```powershell
Get-ChildItem -Path "$env:APPDATA\Claude\local-agent-mode-sessions" -Recurse -Filter "MEMORY.md" |
    Where-Object { $_.FullName -like "*\spaces\*\memory\MEMORY.md" }
```
Передай найденный путь в `prepare-handoff.ps1 -MemoryDir <path>`.

**Workspace folder не подхватывает CLAUDE.md:** убедиться что `C:\Users\V\Documents\Claude\Projects\Velum\CLAUDE.md` существует (он в git, должен подтянуться по `git clone`).

**`bench-models.bat` падает:**
- Docker — иконка кита в трее зелёная?
- Ollama — `curl http://localhost:11434/api/tags` возвращает JSON?
- `qwen2.5:7b-instruct-q4_K_M` есть в `ollama list`? Если нет, скрипт сам пуллит, но это занимает 5-15 мин.
- `gemma4:26b` есть? Аналогично (это MoE-вариант ~18 GB).

**Git pull спрашивает credentials:** Git Credential Manager откроет браузер один раз, подтвердишь GitHub-сессию, дальше работает молча.

**Project instructions не загружаются:** проверь Cowork settings -> проект Velum -> Project instructions, должен быть ровно тот текст из секции 5 выше.

---

## 9. Roadmap после переезда

После того как сравнение моделей будет проанализировано:

- **Краткосрочно (на ПК #2):** добавить продвинутые edge cases в test/, расширить ground truth до ~700 сущностей, попробовать Phase 8 (Tauri desktop client) на 3090.
- **Среднесрочно (когда IT поднимет GPU-сервер):** v0.4.1 — auto-update Tauri клиент, WebSocket streaming сущностей в UI.
- **Долгосрочно:** v0.5 multi-tenant, v0.6 audit + security review + продакшн-launch.

Все эти этапы — для отдельной сессии после успешного завершения текущего бенчмарка.
