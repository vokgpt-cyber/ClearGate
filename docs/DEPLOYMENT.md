# Deployment Guide — VELUM

Полная инструкция по развёртыванию VELUM в трёх конфигурациях: Alpha (ноутбук разработчика), MVP (рабочая станция), Final (кластер ЕПАМ).

## Архитектура развёртывания

```
┌─────────────────────────────────────────────────────────┐
│                  ALPHA (Dev)                            │
│  ASUS ROG G14 / RTX 4060 / 16-32GB RAM                  │
│  Docker Compose (single host)                           │
│  Qwen 2.5 7B Q4 / spaCy / GLiNER medium                 │
│  1 user, ~12s per 10 pages                              │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│                  MVP (Test)                             │
│  Workstation / RTX 3090 / i9 14900KF / 64GB             │
│  Docker Compose with overrides                          │
│  Qwen 2.5 32B Q4 / spaCy / GLiNER large                 │
│  1-3 users, ~3s per 10 pages                            │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│                  FINAL (Production)                     │
│  Server cluster / 2-4× A100/H200 / 512+GB RAM           │
│  Kubernetes                                             │
│  Qwen 2.5 72B FP16 / fine-tuned BERT / DeepSeek-V3      │
│  50-200+ users, <1s per 10 pages, HA                    │
└─────────────────────────────────────────────────────────┘
```

## Alpha — Docker Compose на ноутбуке

### Требования
- Windows 11 / macOS / Linux
- 16 ГБ RAM (24 ГБ с запасом)
- RTX 4060 (8 ГБ VRAM) или эквивалент
- 100 ГБ свободного места на диске
- Docker Desktop с GPU support
- См. также `docs/DEVELOPMENT.md`

### Развёртывание

```powershell
# 1. Клонировать / распаковать
cd D:\Projects
git init velum && cd velum
# (или распаковать архив)

# 2. Setup
.\scripts\setup-dev.ps1

# 3. Скачать модели
.\scripts\download-models.ps1 -Profile alpha

# 4. Заполнить .env
notepad .env
# Минимум: ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, VELUM_MASTER_KEY

# 5. Запустить
docker compose up -d

# 6. Проверка
curl http://localhost:8000/health
```

Frontend запускается отдельно через Tauri:
```powershell
cd frontend
npm run tauri dev
```

### Мониторинг (Alpha)
```powershell
# Логи
docker compose logs -f backend
docker compose logs -f ollama

# Использование GPU
nvidia-smi --loop=1

# Использование диска
docker system df
```

### Обновление
```powershell
# Бэкап перед обновлением
.\scripts\backup.ps1

# Получить новые изменения
git pull   # если используется удалённый репо
# или скопировать новые файлы

# Перебилдить и перезапустить
docker compose build --no-cache
docker compose up -d --force-recreate
```

## MVP — Workstation

### Требования
- Intel i9 14900KF или эквивалент
- 64 ГБ DDR5 RAM
- RTX 3090 (24 ГБ VRAM)
- 2 ТБ NVMe SSD
- Windows 11 Pro / Ubuntu 22.04 LTS
- Docker Desktop / Docker Engine

### Развёртывание

Аналогично Alpha, но с MVP overrides:

```powershell
# 1. Базовый setup как для Alpha
# ...

# 2. Скачать MVP модели
.\scripts\download-models.ps1 -Profile mvp
# Скачается Qwen 2.5 32B (~20 ГБ)

# 3. Запустить с MVP overrides
docker compose -f docker-compose.yml -f docker-compose.mvp.yml up -d
```

### Конфигурация MVP

```yaml
# docker-compose.mvp.yml
services:
  backend:
    environment:
      - VELUM_PROFILE=mvp
      - OLLAMA_MODEL=qwen2.5:32b-instruct-q4_K_M
      - GLINER_MODEL=urchade/gliner_large-v2.1
      - BACKEND_WORKERS=2
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G

  ollama:
    deploy:
      resources:
        limits:
          memory: 24G
```

### Производительность MVP
- Qwen 2.5 32B даёт качество, близкое к GPT-4o на русском
- Анонимизация 10-страничного документа: ~3 секунды
- Параллельных пользователей: 1-3 (зависит от размера документов)
- VRAM: ~22 ГБ из 24 (с запасом на KV-cache)

## Final — Production кластер

### Требования
- Серверный кластер с минимум 3 узлами:
  - 2× GPU-узла (по 2-4 NVIDIA A100/H200)
  - 1× Application-узел (CPU only, FastAPI workers)
  - Опц. 1× DB-узел (PostgreSQL для аудита)
- 512 ГБ - 1 ТБ ECC RAM на каждом узле
- NVMe RAID + объектное хранилище для бэкапов
- 10 GbE интерконнект между узлами
- Линия в дата-центр ЕПАМ
- Linux (Ubuntu 22.04 LTS / RHEL 9)
- Kubernetes 1.30+
- NVIDIA GPU Operator

### Архитектура

```
              ┌──────────────────────┐
              │   Load Balancer      │
              │   (HAProxy / Nginx)  │
              └──────────┬───────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼──────┐  ┌──────▼─────┐  ┌──────▼─────┐
   │ Frontend  │  │ Frontend   │  │ Frontend   │
   │ Replica 1 │  │ Replica 2  │  │ Replica 3  │
   └────┬──────┘  └──────┬─────┘  └──────┬─────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
              ┌──────────▼───────────┐
              │ Backend API Pods     │
              │ (FastAPI workers)    │
              │ HPA: 3-20 replicas   │
              └──────────┬───────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼──────┐  ┌──────▼─────┐  ┌──────▼─────┐
   │ NER Pod   │  │ NER Pod    │  │ NER Pod    │
   │ (GPU 1)   │  │ (GPU 2)    │  │ (GPU 3)    │
   │ Qwen 72B  │  │ Qwen 72B   │  │ Qwen 72B   │
   └───────────┘  └────────────┘  └────────────┘
                         │
              ┌──────────▼───────────┐
              │ PostgreSQL (HA)      │
              │ для аудита           │
              └──────────────────────┘
              ┌──────────────────────┐
              │ Redis (HA)           │
              │ для сессий           │
              └──────────────────────┘
```

### Развёртывание

```bash
# 1. Подготовить namespace
kubectl create namespace velum

# 2. Создать secrets
kubectl create secret generic velum-api-keys \
    --from-literal=anthropic-api-key=sk-ant-... \
    --from-literal=openai-api-key=sk-... \
    --from-literal=google-api-key=AIza... \
    --from-literal=velum-master-key=... \
    -n velum

# 3. Применить конфигурацию
kubectl apply -f k8s/

# 4. Проверить статус
kubectl get pods -n velum
kubectl logs -f deployment/velum-backend -n velum
```

### Структура k8s/

```
k8s/
├── namespace.yaml
├── configmaps/
│   └── velum-config.yaml
├── secrets/
│   └── velum-secrets.yaml.example
├── deployments/
│   ├── backend.yaml
│   ├── frontend.yaml
│   ├── ollama.yaml          # GPU node selector
│   └── postgres.yaml
├── services/
│   ├── backend-svc.yaml
│   ├── frontend-svc.yaml
│   └── ollama-svc.yaml
├── ingress/
│   └── velum-ingress.yaml
├── hpa/
│   └── backend-hpa.yaml
├── pdb/
│   └── backend-pdb.yaml
└── monitoring/
    ├── prometheus-rules.yaml
    └── grafana-dashboard.json
```

### Production checklist

- [ ] Master key хранится в HashiCorp Vault / AWS Secrets Manager (не в k8s secrets)
- [ ] TLS 1.3 для всех внешних соединений
- [ ] Network policies изолируют namespaces
- [ ] PostgreSQL с репликацией (минимум 1 standby)
- [ ] Backup PostgreSQL: ежедневно + WAL archiving
- [ ] Backup k8s manifests в git
- [ ] Мониторинг через Prometheus + Grafana
- [ ] Logs через Loki / Elasticsearch (без PII!)
- [ ] Алерты на ошибки 5xx, всплески latency, downtime моделей
- [ ] HPA настроен (CPU + memory + custom metrics)
- [ ] PodDisruptionBudget предотвращает падение всех реплик при maintenance
- [ ] Rolling updates без downtime
- [ ] Регулярные DR-тесты: восстановление из backup в изолированном кластере
- [ ] Penetration testing перед продакшн запуском
- [ ] Security audit (внешний)

### Производительность Final
- Параллельных пользователей: 50-200+
- Анонимизация документа на 10 страниц: <1 секунда
- Пакетная обработка: 1000+ документов в час
- Uptime SLA: 99.9% (≤ 8.7 часов downtime в год)

## Откат (rollback)

### Alpha/MVP
```powershell
# Откатиться на предыдущий коммит
git reset --hard HEAD~1
docker compose up -d --force-recreate
```

### Final
```bash
kubectl rollout undo deployment/velum-backend -n velum
kubectl rollout status deployment/velum-backend -n velum
```

## Disaster recovery

| Сценарий | Действия |
|----------|----------|
| Pod упал | Auto-restart через k8s |
| GPU node упал | HPA перенаправит на другие GPU pods |
| Все backend pods упали | Manual rollback + investigation |
| База потеряна | Restore из последнего PostgreSQL backup (RPO 1 час) |
| Весь кластер потерян | Restore manifests из git, БД из off-site backup, секреты из Vault |

См. также `docs/BACKUP.md`.

## Capacity planning

### Расчёт ресурсов на пользователя (Final)

| Ресурс | На пользователя | На 100 пользователей |
|--------|-----------------|----------------------|
| RAM (Backend) | ~500 МБ | 50 ГБ |
| VRAM (NER) | shared, ~24 ГБ всего | 24 ГБ × количество GPU pods |
| CPU | 0.5 cores | 50 cores |
| Storage (logs/audit) | 10 МБ/день | 1 ГБ/день |

### Когда масштабировать вверх

Триггеры для увеличения ресурсов:
- p95 latency > 5 секунд → добавить GPU pods
- CPU utilization > 70% → увеличить backend HPA max
- Memory pressure → увеличить limits
- LLM API queue > 30 секунд → добавить fallback провайдеров
