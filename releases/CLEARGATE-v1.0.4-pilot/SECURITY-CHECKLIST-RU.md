# Security checklist for IT

Основной аудит лежит в корне репозитория: `SECURITY-AUDIT-PILOT-RU.md`.

После `git pull` и пересборки обязательно выполнить:

```bash
cd /opt/cleargate
./releases/CLEARGATE-v1.0.4-pilot/scripts/smoke-test.sh

docker port cleargate-backend 8000/tcp
docker port cleargate-frontend 3000/tcp
docker port cleargate-ollama 11434/tcp
docker port cleargate-bge 80/tcp
```

Ожидаемо все внутренние сервисы должны быть опубликованы только на `127.0.0.1` или `[::1]`.
Снаружи пользователям должны быть доступны только `443` и, если нужно, `80`.

Критично: настроить host firewall/egress policy для Docker-контейнеров. Если контейнер будет скомпрометирован, без egress policy он сможет пытаться ходить во внутреннюю корпоративную сеть. Минимальный allowlist: внутренние зеркала пакетов/моделей, DNS/NTP при необходимости, AD/LDAP только если включена LDAP-аутентификация.
