# CLEARGATE v1.0.4: инструкция для IT по разворачиванию пилота

Документ описывает развертывание CLEARGATE `v1.0.4` на Ubuntu-сервере с
NVIDIA GPU. Предполагается, что IT имеет доступ к GitHub-репозиторию:

`https://github.com/vokgpt-cyber/ClearGate.git`

## 1. Целевая схема

На сервере поднимается Docker Compose stack:

- `frontend` - веб-интерфейс CLEARGATE;
- `backend` - FastAPI backend, хранение сессий, пользователей и документов;
- `nginx` - единая точка входа по HTTPS;
- `vllm` - локальный GPU LLM/verifier;
- `bge-embedder` - локальный multilingual embedder для retrieval/QA слоя;
- `cleargate-data` - persistent volume для SQLite, сессий, документов, ключей;
- `cleargate-models` - persistent volume для HF/vLLM/BGE моделей.

Пользователи открывают только один URL:

```text
https://<CLEARGATE_DOMAIN>
```

Внешние облачные LLM из CLEARGATE не вызываются. Если пользователь скачивает
анонимизированный DOCX и сам загружает его в облачную LLM, это уже отдельный
ручной шаг в пользовательском процессе.

## 2. Требования к серверу

Минимум для пилота:

- Ubuntu 22.04 LTS или 24.04 LTS;
- NVIDIA GPU класса RTX 4090/48 GB или близкий по VRAM серверный GPU;
- NVIDIA driver установлен на host;
- Docker Engine 24+;
- Docker Compose v2.24+;
- NVIDIA Container Toolkit;
- 80 GB свободного места под Docker images, модели и данные;
- сетевой доступ к GitHub и HuggingFace на время установки моделей;
- inbound порт `443` для пользователей;
- inbound порт `80` на время Let's Encrypt, если выбран `CLEARGATE_TLS_MODE=letsencrypt`.

Рекомендуемо:

- отдельный DNS alias, например `cleargate-test.company.local`;
- corporate TLS certificate или внутренний CA;
- регулярный backup persistent volume `cleargate-data`;
- ограниченный доступ к серверу только для IT/admin.

## 3. Подготовить сервер

Зайти на сервер пользователем с правом `sudo`.

Проверить GPU:

```bash
nvidia-smi
```

Проверить Docker, если уже установлен:

```bash
docker --version
docker compose version
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Если Docker или NVIDIA Container Toolkit не установлены, installer попробует
установить их сам. Если у вашей IT-политики есть стандартный способ установки
Docker/NVIDIA runtime, лучше выполнить его заранее.

## 4. Получить код из GitHub

Рекомендуемый путь установки: `/opt/cleargate`.

```bash
sudo mkdir -p /opt/cleargate
sudo chown "$USER:$USER" /opt/cleargate
git clone https://github.com/vokgpt-cyber/ClearGate.git /opt/cleargate
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
```

Если репозиторий уже есть:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
```

Контроль:

```bash
cat releases/CLEARGATE-v1.0.4-pilot/VERSION.lock
git log --oneline --decorate -3
```

В `VERSION.lock` должна быть строка:

```text
Application version: 1.0.4
Application tag: v1.0.4
Application baseline commit: 38077abbb0d8b1536479094880971914d0a730af
```

## 5. Запустить установщик

```bash
cd /opt/cleargate
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

Installer делает:

1. Проверяет Ubuntu, NVIDIA driver, GPU memory.
2. Проверяет или устанавливает Docker Engine.
3. Проверяет или устанавливает NVIDIA Container Toolkit.
4. Проверяет, что GPU виден внутри Docker.
5. Создает `/opt/cleargate/certs`, `/opt/cleargate/backups`, `/opt/cleargate/logs`.
6. Создает `.env` из `.env.pilot.example`, если `.env` отсутствует.
7. Спрашивает домен и TLS mode.
8. Генерирует self-signed certificate или подключает corporate/Let's Encrypt cert.
9. Собирает backend/frontend images.
10. Поднимает `vllm`, `bge-embedder`, `backend`, `frontend`, `nginx`.
11. Дожидается healthchecks.
12. Создает локального admin-пользователя, если база пользователей пустая.
13. Создает systemd service `cleargate.service`.

Первый запуск может занять 15-40 минут из-за загрузки моделей:

- `Qwen/Qwen3-32B-AWQ`;
- `BAAI/bge-m3`.

Pinned inference images для pilot.3:

- `VLLM_IMAGE=vllm/vllm-openai:v0.9.2` - версия с поддержкой Qwen3. Старый
  `v0.7.3` падает с `KeyError: 'qwen3'` / `Transformers does not recognize this architecture`;
- `TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:89-1.9` - Ada/RTX
  4090 compatible TEI build для BGE-M3. Старый `1.5` может падать на скачивании
  артефактов BGE с `relative URL without a base`.

Если организация использует внутреннее зеркало HuggingFace, задайте в `.env`:

```bash
HF_ENDPOINT=https://hf-mirror.company.local
HF_HUB_DISABLE_XET=1
HF_TOKEN=<optional-token>
```

`HF_ENDPOINT` обязан быть абсолютным URL с `http://` или `https://`; installer
остановится до запуска Docker, если значение похоже на относительный путь.

Важно про spaCy: pilot.2 не использует `python -m spacy download` во время
Docker build, потому что эта команда зависит от `raw.githubusercontent.com` и
часто падает в корпоративных сетях с SSL EOF. Вместо этого обязательная модель
`ru_core_news_lg` ставится из direct wheel URL GitHub Releases и проверяется
во время сборки. Backend не должен запускаться без этой модели: это quality
gate, чтобы не снижать качество анонимизации.

Если доступ к GitHub release assets тоже закрыт, IT должен заранее скачать
wheel, положить его во внутренний mirror и указать в `.env`:

```bash
SPACY_MODEL=ru_core_news_lg
SPACY_MODEL_WHEEL_URL=https://internal-mirror/ru_core_news_lg-3.8.0-py3-none-any.whl
```

И пересобрать backend:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml \
  --profile gpu build backend
```

## 6. TLS modes

### selfsigned

Самый быстрый режим для лаборатории.

В `.env`:

```bash
CLEARGATE_TLS_MODE=selfsigned
CLEARGATE_DOMAIN=cleargate.local
```

Минус: браузер будет показывать предупреждение о сертификате.

### corp_ca

Рекомендуемый режим для внутренней тестовой группы.

До запуска положить сертификаты:

```text
/opt/cleargate/certs/<CLEARGATE_DOMAIN>.crt
/opt/cleargate/certs/<CLEARGATE_DOMAIN>.key
```

В `.env`:

```bash
CLEARGATE_TLS_MODE=corp_ca
CLEARGATE_DOMAIN=cleargate-test.company.local
```

Installer сделает symlink:

```text
/opt/cleargate/certs/active.crt
/opt/cleargate/certs/active.key
```

### letsencrypt

Использовать только если домен публично резолвится и порт `80` доступен из
интернета для HTTP-01 challenge.

В `.env`:

```bash
CLEARGATE_TLS_MODE=letsencrypt
CLEARGATE_DOMAIN=cleargate.example.com
```

## 7. Проверка после установки

Статус:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/status-cleargate.sh
```

Smoke test:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/smoke-test.sh
```

Логи:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/logs-cleargate.sh
```

## 7.1 Если предыдущая установка упала на `spacy download`

Симптом:

```text
RUN python -m spacy download ru_core_news_sm
SSLEOFError ... raw.githubusercontent.com/explosion/spacy-models/master/compatibility.json
```

Исправление:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

После hotfix `pilot.2` Dockerfile больше не выполняет `python -m spacy download`.
Installer принудительно выставит `SPACY_MODEL=ru_core_news_lg` и direct wheel
URL. Если сервер не может скачать wheel с GitHub Releases, не отключайте
модель: скачайте wheel через разрешенный канал, положите во внутренний mirror и
замените `SPACY_MODEL_WHEEL_URL` в `.env`, затем повторите установку.

## 7.2 Если `cleargate-vllm` падает на `model_type qwen3`

Симптом:

```text
KeyError: 'qwen3'
ValueError: Transformers does not recognize this architecture
```

Причина: старый `vllm/vllm-openai:v0.7.3` не поддерживает Qwen3.

Исправление:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
grep '^VLLM_IMAGE=' .env
```

Должно быть:

```bash
VLLM_IMAGE=vllm/vllm-openai:v0.9.2
```

Если строка отсутствует, installer добавит ее автоматически. После обновления:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

## 7.3 Если `cleargate-bge` падает с `relative URL without a base`

Симптом:

```text
Error: Could not download model artifacts
request error: builder error: relative URL without a base
```

Проверьте:

```bash
grep -E '^(TEI_IMAGE|HF_ENDPOINT|HF_HUB_DISABLE_XET|EMBEDDER_MODEL)=' .env
```

Рекомендуемые значения для RTX 4090 / Ada GPU:

```bash
TEI_IMAGE=ghcr.io/huggingface/text-embeddings-inference:89-1.9
HF_ENDPOINT=https://huggingface.co
HF_HUB_DISABLE_XET=1
EMBEDDER_MODEL=BAAI/bge-m3
```

Если используется внутреннее зеркало HF, `HF_ENDPOINT` должен быть абсолютным:

```bash
HF_ENDPOINT=https://hf-mirror.company.local
```

Открыть в браузере:

```text
https://<CLEARGATE_DOMAIN>
```

Admin password installer сохраняет в root-only файл:

```text
/opt/cleargate/initial-admin-password.txt
```

Права файла: `600`. После передачи доступа администратору пароль желательно
сменить через CLI или создать новых пользователей в админке.

## 8. Управление сервисом

Старт:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/start-cleargate.sh
```

Остановка:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/stop-cleargate.sh
```

Статус:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/status-cleargate.sh
```

Systemd:

```bash
sudo systemctl status cleargate.service
sudo systemctl start cleargate.service
sudo systemctl stop cleargate.service
sudo systemctl restart cleargate.service
```

## 9. Пользователи

До подключения LDAP/AD пользователи локальные.

Список:

```bash
docker exec -it cleargate-backend cleargate-admin list-users
```

Создать администратора:

```bash
docker exec -it cleargate-backend cleargate-admin create-user vadim --admin
```

Создать обычного пользователя:

```bash
docker exec -it cleargate-backend cleargate-admin create-user lawyer1
```

Сбросить пароль:

```bash
docker exec -it cleargate-backend cleargate-admin reset-password lawyer1
```

Заблокировать:

```bash
docker exec -it cleargate-backend cleargate-admin set-active lawyer1 --active false
```

## 10. Backup

Сделать backup:

```bash
bash releases/CLEARGATE-v1.0.4-pilot/scripts/backup-cleargate.sh
```

Backup включает:

- git bundle исходников;
- архив Docker volume `cleargate-data`;
- `.env`;
- TLS certs metadata;
- последние логи.

Папка backup:

```text
/opt/cleargate/backups/<timestamp>/
```

Важно: backup содержит документы и персональные данные до/после
анонимизации. Хранить только на защищенном encrypted storage.

## 11. Restore

Восстановление заменяет текущий `cleargate-data`.

```bash
RESTORE_I_UNDERSTAND=1 bash releases/CLEARGATE-v1.0.4-pilot/scripts/restore-cleargate.sh /opt/cleargate/backups/<timestamp>
```

Перед restore сделать новый backup текущего состояния.

## 12. Update в рамках пилота

Если появится hotfix для release-ветки:

```bash
cd /opt/cleargate
bash releases/CLEARGATE-v1.0.4-pilot/scripts/update-cleargate.sh
```

Скрипт:

1. Делает backup.
2. Делает `git fetch`.
3. Обновляет `release/pilot-v1.0.4` через `git pull --ff-only`.
4. Пересобирает images.
5. Перезапускает stack.
6. Запускает smoke test.

## 13. Откат

Быстрый rollback к baseline app commit:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git reset --hard 38077abbb0d8b1536479094880971914d0a730af
git checkout release/pilot-v1.0.4 -- releases/CLEARGATE-v1.0.4-pilot
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml \
  --profile gpu up -d --build
```

Если надо восстановить данные, использовать restore из backup.

## 14. Что передать тестовой группе

1. URL приложения.
2. Логины.
3. Простую инструкцию `README-USERS-RU.md`.
4. Канал для обратной связи.
5. Список тестовых сценариев:
   - один DOCX;
   - несколько DOCX в одну сессию;
   - PDF;
   - скачать анонимизированный DOCX;
   - загрузить ответ LLM;
   - сравнить;
   - деанонимизировать;
   - скачать итоговый DOCX.

## 15. Что мониторить во время пилота

- Свободное место:

```bash
df -h
docker system df
```

- GPU:

```bash
nvidia-smi
```

- Контейнеры:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml \
  --profile gpu ps
```

- Логи backend:

```bash
docker logs --tail 200 -f cleargate-backend
```

- Логи vLLM:

```bash
docker logs --tail 200 -f cleargate-vllm
```

## 16. Известная пометка для Deep scan

LLM/verifier включен и работает локально на сервере. В пользовательской
инструкции он описан как дополнительная проверка. На текущей версии он не
является главным механизмом качества и иногда может предлагать спорные правки.

Рекомендуемая политика пилота:

- основной результат проверять после обычной анонимизации;
- Deep scan включать только если есть сомнения;
- внимательно смотреть предложения Deep scan;
- при спорном результате Deep scan отключать его слой обратно.
