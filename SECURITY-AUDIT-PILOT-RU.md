# CLEARGATE pilot security audit

Дата: 2026-05-08

Область проверки: кодовая база и Docker/release-файлы, которые передаются IT для пилотного разворачивания. Прямого доступа к серверу IT из этой среды нет, поэтому серверные проверки ниже должны быть выполнены IT на хосте `/opt/cleargate`.

## Что исправлено в этом security pass

- `backend` и `frontend` в GPU-профиле больше не публикуются наружу на все интерфейсы. Они привязаны к `127.0.0.1`, публичной точкой входа остается только `nginx` на `80/443`.
- Auth-cookie в HTTPS/release-профиле теперь выставляется с флагом `Secure`.
- Для `backend`, `frontend` и `nginx` включен `no-new-privileges`; для `backend` и `frontend` сброшены Linux capabilities.
- Добавлен мягкий rate limit на неудачные попытки логина, чтобы снизить риск перебора локальных учеток.
- Добавлена защита от подозрительных DOCX-пакетов: слишком много внутренних файлов, path traversal внутри zip, чрезмерный uncompressed size, подозрительный compression ratio.
- Для feedback screenshot ограничен размер payload, чтобы API нельзя было использовать как простой способ раздувать SQLite/volume.
- Frontend Docker build переведен на `npm ci`.
- Next обновлен до `15.5.18`, `postcss` зафиксирован на `8.5.10`; `npm audit --omit=dev` теперь показывает `0` уязвимостей.
- Smoke-test release-пакета теперь проверяет, что `backend:8000` и `frontend:3000` доступны только через loopback.

## Что проверено локально

- `docker compose --profile gpu -f docker-compose.yml -f docker-compose.gpu.yml -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml config --quiet` — OK.
- `npm --prefix frontend run typecheck` — OK.
- `npm --prefix frontend run build` — OK.
- `npm --prefix frontend audit --omit=dev --json` — `0` уязвимостей.
- `python -m pip_audit backend --format json` — известных Python-уязвимостей не найдено.
- `python -m compileall backend/app` — OK.

Полный `pytest` локально не запускался, потому что в текущем Python окружении нет `pytest`. На сервере или CI стоит прогонять backend tests отдельно.

## Что IT должно проверить после обновления

```bash
cd /opt/cleargate
git pull

docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml \
  --profile gpu up -d --build

./releases/CLEARGATE-v1.0.4-pilot/scripts/smoke-test.sh
```

Проверить порты:

```bash
docker port cleargate-backend 8000/tcp
docker port cleargate-frontend 3000/tcp
docker port cleargate-vllm 8000/tcp
docker port cleargate-bge 80/tcp
```

Ожидаемо:

- `cleargate-backend` должен показывать только `127.0.0.1:8000` или `[::1]:8000`.
- `cleargate-frontend` должен показывать только `127.0.0.1:3000` или `[::1]:3000`.
- `cleargate-vllm` должен показывать только `127.0.0.1:8001`.
- `cleargate-bge` должен показывать только `127.0.0.1:8002`.
- Снаружи корпоративной сети пользователям должны быть доступны только `443` и, при необходимости, `80` для redirect/сертификатов.

Проверить cookie после логина в DevTools браузера:

- cookie `cg_session` должна быть `HttpOnly`, `Secure`, `SameSite=Lax`.

## Обязательные инфраструктурные меры

Эти пункты не могут быть полностью закрыты кодом приложения, но критичны для защиты корпоративной сети и документов.

1. Закрыть внешние порты на firewall/security group: наружу только `443` и опционально `80`. Порты `3000`, `8000`, `8001`, `8002`, `11434` не должны быть доступны с пользовательских машин.
2. Ограничить egress контейнеров через `DOCKER-USER`/firewall/proxy. Если контейнер будет скомпрометирован, без egress policy он сможет пытаться сканировать внутреннюю сеть. Минимальный allowlist: внутренние зеркала packages/models, DNS/NTP при необходимости, AD/LDAP только если включена LDAP-аутентификация.
3. Хранить `/var/lib/docker/volumes/cleargate-data` и backup-директорию на зашифрованном диске. Сейчас исходные, анонимизированные и деанонимизированные документы лежат в Docker volume в обычном виде; registry/mapping шифруется, но сами DOCX/PDF и SQLite/backups должны защищаться инфраструктурно.
4. Шифровать backups перед выносом с сервера и ограничить доступ к backup-каталогу. Backup содержит пользовательские документы и может содержать `.env`.
5. Хранить `.env` с правами `600`, владелец `root` или сервисный deploy-user. LDAP bind password, HF token и cookie secret не должны попадать в issue tracker, чаты или screenshots.
6. Для пилота допустим self-signed TLS, но для тестовой группы лучше корпоративный CA-сертификат, чтобы пользователи не привыкали нажимать `Proceed to unsafe site`.
7. Перед расширением пилота просканировать runtime images корпоративным scanner'ом и по возможности перейти на digest-pinned images/internal registry.

## Остаточные риски и следующие hardening-шаги

- Контейнеры пока работают root-процессами внутри контейнера. Следующий безопасный шаг: отдельный non-root user + миграция владельца существующего `cleargate-data` volume.
- Python-зависимости backend пока задаются диапазонами в `pyproject.toml`; для production нужен lock/constraints файл и сборка из внутреннего wheelhouse/mirror.
- Модельные артефакты HuggingFace и Docker images пока фиксируются тегами/именами, не digest/hash. Для production нужен внутренний vetted mirror.
- CSRF-токена нет; риск частично снижен `SameSite=Lax`, JSON API и отсутствием публичной CORS-дырки, но для production стоит добавить CSRF-token на state-changing endpoints.
- Rate limit логина in-memory и per-container-worker. Для нескольких backend replicas нужен Redis/DB-backed limiter или внешний WAF/rate limit на nginx.
- Логи не должны содержать текст документов. Сейчас приложение логирует метаданные и счетчики; IT все равно нужно ограничить доступ к `./logs` и включить retention.

## Главный вывод

После этого pass наиболее опасная ошибка deployment-периметра закрыта: внутренние сервисы больше не должны торчать в сеть мимо nginx. Для предотвращения компрометации корпоративной сети ключевой следующий контроль находится у IT: хостовый firewall/egress policy для Docker-контейнеров и шифрованное хранение volumes/backups.
