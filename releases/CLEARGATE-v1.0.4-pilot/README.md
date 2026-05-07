# CLEARGATE v1.0.4 Pilot Package

Это релизный пакет для разворачивания CLEARGATE `v1.0.4` на Ubuntu-сервере с NVIDIA GPU.

Главные файлы:

- `README-DEPLOY-RU.md` - подробная инструкция для IT.
- `README-USERS-RU.md` - простая инструкция для тестовых пользователей.
- `RELEASE-NOTES.md` - что входит в пилотную версию и какие есть ограничения.
- `VERSION.lock` - зафиксированная версия приложения и baseline commit.
- `.env.pilot.example` - шаблон настроек сервера.
- `scripts/install-cleargate.sh` - основной установщик.
- `scripts/status-cleargate.sh` - проверка состояния.
- `scripts/backup-cleargate.sh` - резервное копирование.
- `scripts/update-cleargate.sh` - обновление в рамках release-ветки.
- `scripts/restore-cleargate.sh` - восстановление из backup.

Короткий путь для IT после доступа к GitHub:

```bash
sudo mkdir -p /opt/cleargate
sudo chown "$USER:$USER" /opt/cleargate
git clone https://github.com/vokgpt-cyber/ClearGate.git /opt/cleargate
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

Если установка уже падала на `python -m spacy download ru_core_news_sm`:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

Начиная с pilot.2 backend Docker build больше не использует
`python -m spacy download`, поэтому не обращается к
`raw.githubusercontent.com` за spaCy compatibility.json. Вместо этого
обязательная модель `ru_core_news_lg` ставится из direct wheel URL GitHub
Releases. Если доступ к GitHub release assets закрыт, IT должен указать
внутренний mirror через `SPACY_MODEL_WHEEL_URL`; запуск без модели запрещен,
чтобы не снижать качество анонимизации.

Если репозиторий уже склонирован:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```
