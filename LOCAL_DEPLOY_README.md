# Cleargate — локальный запуск на ПК #2 (RTX 3090, 64 GB RAM)

Это **самый простой** способ потрогать Cleargate на твоём втором компе. Никакого vLLM, никакого LDAP, никакого TLS. Заводится одной командой и работает через `http://localhost`.

---

## Что нужно подготовить (один раз)

1. **Docker Desktop** — установлен и запущен. Иконка кита в трее должна быть зелёная. Если не запущен, открой Docker Desktop из меню Пуск.

2. **Ollama** — установлен и работает. Проверка: открой PowerShell и набери:
   ```powershell
   curl http://localhost:11434/api/tags
   ```
   Должен прийти JSON со списком моделей. Если ошибка — запусти Ollama (либо через десктопное приложение, либо командой `ollama serve`).

3. **Модель Qwen 2.5 7B** — желательно уже скачана. Проверка:
   ```powershell
   ollama list
   ```
   Если в списке есть `qwen2.5:7b-instruct-q4_K_M` — отлично, ничего делать не надо. Если нет — стартовый скрипт скачает сам (5-15 минут).

   Если хочешь модель помощнее (на RTX 3090 с 24 GB VRAM она спокойно влезет), скачай заранее:
   ```powershell
   ollama pull qwen2.5:14b-instruct-q4_K_M
   ```
   и потом запускай скрипт с переменной:
   ```powershell
   $env:OLLAMA_MODEL = "qwen2.5:14b-instruct-q4_K_M"
   .\scripts\start-local.bat
   ```

4. **Папка проекта** — пусть будет `C:\Users\V\Documents\Claude\Projects\Velum` (как на ноуте). Скопируй её на ПК #2 целиком, либо клонируй из git.

---

## Запуск (одна команда)

В PowerShell или cmd, из папки `Velum`:

```powershell
.\scripts\start-local.bat
```

Что произойдёт:
1. Скрипт проверит Docker.
2. Скрипт проверит Ollama.
3. Если модели нет — скачает.
4. Соберёт Docker-образы backend + frontend (первый раз ~5-10 минут).
5. Запустит контейнеры.
6. Подождёт пока всё станет healthy.
7. Откроет браузер на `http://localhost`.

**Логин:** `admin` / `adminadmin`

Можно сразу загружать тестовый `.docx` и анонимизировать.

---

## Производительность чего ждать

На RTX 3090 + Qwen 2.5 7B (Q4):
- Регексы (Layer 1): мгновенно
- spaCy (Layer 2): 0.5-2 сек на документ; GLiNER в local-профиле выключен по умолчанию, чтобы первый запуск не тянул модель с HuggingFace
- LLM verify (Layer 4): 3-8 сек на документ (continuous batching у Ollama)
- LLM scan (Layer 5): 3-8 сек

**Итого: 7-20 сек на типичный юр. документ.** Это сравнимо с production GPU (vLLM + 32B был бы 7-25 сек).

BGE retrieval (Layer 3) **отключён** в этом профиле — pipeline переходит в graceful degradation: вместо точечного контекста к LLM уходит весь документ. Качество чуть-чуть просядет на длинных бумагах (>20 страниц), но в большинстве случаев это незаметно.

---

## Проверить что всё работает

После старта в новом окне терминала:

```powershell
# Все 3 контейнера должны быть в статусе "Up"
docker ps --filter "name=cleargate-local-"

# Должно вернуть {"status":"healthy"} или похожее
curl http://localhost/health

# Открыть UI
start http://localhost
```

---

## Остановить

```powershell
.\scripts\stop-local.bat
```

Контейнеры удаляются, **данные (юзеры, сессии, audit log) сохраняются** в томе `cleargate-local-data`. При следующем запуске всё на месте.

Если хочешь полностью обнулить (например для чистого теста):
```powershell
docker compose -f docker-compose.local.yml down -v
```

---

## Что-то пошло не так

| Симптом | Что делать |
|---------|------------|
| `docker info` ошибка | Открыть Docker Desktop, дождаться зелёной иконки |
| `Ollama is not reachable` | Запустить Ollama (десктопное приложение или `ollama serve`) |
| Браузер пишет `connection refused` на :80 | Подожди ещё 30-60 секунд (frontend поднимается медленно при первой сборке), потом обнови |
| Анонимизация очень медленная | Проверь что Ollama использует GPU: `nvidia-smi` должен показать процесс ollama |
| Логин не пускает | Точно `admin` / `adminadmin` (нижний регистр) |

Логи всех контейнеров одной командой:
```powershell
docker compose -f docker-compose.local.yml logs --tail 200
```

Логи только бэкенда:
```powershell
docker logs --tail 200 cleargate-local-backend
```

---

## Чем этот профиль ОТЛИЧАЕТСЯ от production v0.4.0

| Параметр | Production (v0.4.0) | Этот профиль (local) |
|----------|---------------------|----------------------|
| LLM | vLLM + Qwen 3 32B AWQ (22 GB VRAM) | Host Ollama + Qwen 2.5 7B (5 GB VRAM) |
| Embedder | BGE-M3 в контейнере | Отключён (graceful degradation) |
| Auth | LDAP / AD | Локальный admin/adminadmin |
| TLS | Да (Let's Encrypt / corp CA) | Нет, plain HTTP |
| URL | `https://<corp-domain>/` | `http://localhost/` |
| Старт | `install-gpu.sh` (Ubuntu) | `start-local.bat` (Windows) |
| Назначение | Боевая работа юристов | Личный тест функциональности |

Если что-то ломается тут, **production v0.4.0-rc1 это никак не затрагивает** — это полностью изолированный compose с новыми именами контейнеров (`cleargate-local-*`).
