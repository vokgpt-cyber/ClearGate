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

Если браузер открывает страницу, но висит на "Проверяем сессию...":

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
bash releases/CLEARGATE-v1.0.4-pilot/scripts/update-cleargate.sh
bash releases/CLEARGATE-v1.0.4-pilot/scripts/smoke-test.sh
```

Начиная с pilot.5 frontend-сборка не должна содержать `localhost` API URL.
Smoke-test отдельно проверяет, что `/api/auth/me` доступен через nginx и без
cookie возвращает нормальный `401`, а не зависает.

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

Начиная с pilot.8 вторичный LLM/verifier переведен на Gemma4 через Ollama:

- `OLLAMA_IMAGE=ollama/ollama:latest`, либо внутренний pinned образ IT,
  совместимый с Gemma4;
- `CLEARGATE_LLM_MODEL=gemma4:26b`;
- `ghcr.io/huggingface/text-embeddings-inference:89-1.9` вместо `1.5` для
  BGE-M3 на RTX 4090 / Ada GPU;
- `HF_ENDPOINT` явно задается как абсолютный URL. Для внутреннего mirror
  используйте, например, `HF_ENDPOINT=https://hf-mirror.company.local`.

Если репозиторий уже склонирован:

```bash
cd /opt/cleargate
git fetch --all --tags
git checkout release/pilot-v1.0.4
git pull --ff-only
bash releases/CLEARGATE-v1.0.4-pilot/scripts/install-cleargate.sh
```

ORG quality hotfix `pilot.7`:

- после обновления backend надо пересобрать, потому что изменилась логика
  NER-пайплайна;
- `CLEARGATE_DEFAULT_GLINER_LABELS` должен быть `person,address` или пустым,
  если IT намеренно доверяет коду по умолчанию;
- не задавайте старое значение с `organization,location`, иначе GLiNER снова
  начнет давать избыточные ORG-кандидаты.

Gemma4 hotfix `pilot.8`:

- после `git pull` запустите `scripts/update-cleargate.sh`;
- скрипт мигрирует старые `OLLAMA_HOST=http://vllm:8000/v1` и
  `OLLAMA_MODEL=cleargate-llm` на `gemma4:26b`;
- если у IT есть внутренний pinned Ollama image от транскрибатора, укажите его
  в `.env` как `OLLAMA_IMAGE=<image>`.

PDF Track Changes hotfix `pilot.11`:

- после `git pull` запустите `scripts/update-cleargate.sh`;
- backend надо пересобрать, потому что изменилась логика извлечения PDF-текста;
- PDF, экспортированные из Word с включенными Track Changes, теперь очищаются
  от зачеркнутых удалений до анонимизации; подчеркнутые вставки остаются.

Quality policy hotfix `pilot.12`:

- после `git pull` запустите `scripts/update-cleargate.sh`;
- backend и frontend надо пересобрать: изменилась логика отбора сущностей и
  поведение Deep Scan в интерфейсе;
- базовый анонимизатор получил policy layer `auto/review/ignore`: в ДМС и
  внутренних политиках он отсекает родовые слова вроде `Сотрудник`,
  `Адвокатское бюро`, публичные сервисы и support-контакты, но сохраняет ФИО,
  номера полисов, даты и конкретные фирмы вроде `Адвокатское бюро ЕПАМ`;
- Deep Scan больше не применяет предложения автоматически. Он показывает QA-
  предложения отдельным списком, а пользователь сам выбирает, что включить.
## Entity engine experiment:

- default remains `CLEARGATE_ENTITY_ENGINE=classic`;
- Gemma4 candidate-map modes are available only as an explicit A/B experiment:
  `gemma_shadow`, `gemma_primary`, `hybrid_consensus`;
- rollback is immediate: set `CLEARGATE_ENTITY_ENGINE=classic` in `.env` and
  recreate backend;
- see `docs/GEMMA_ENTITY_MAP_EXPERIMENT.md` in the repository for the current
  golden-corpus comparison. On the committed synthetic set, classic is faster
  and matches Gemma modes on quality, so do not enable Gemma entity-map modes
  for pilot users by default.
