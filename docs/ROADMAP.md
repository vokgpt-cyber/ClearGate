# CLEARGATE Roadmap

Дорожная карта развития от прототипа до продакшн-системы для всего штата ЕПАМ.

## Обзор

| Версия | Цель | Срок | Статус |
|--------|------|------|--------|
| **0.1.0-alpha** | Работающий прототип на ноутбуке | 2-4 недели | 🚧 В разработке |
| **0.2.0-mvp** | Тестирование на рабочей станции, все 3 LLM | 2-3 месяца | 📅 Планируется |
| **0.3.0** | Multi-user, audit, расширенные фичи | 4-6 месяцев | 📅 Планируется |
| **1.0.0-final** | Production на серверах ЕПАМ, весь штат | 7-12 месяцев | 📅 Планируется |

## v0.1.0-alpha — Working Prototype

**Срок:** 2-4 недели от старта
**Конфигурация:** ASUS ROG G14, RTX 4060, Windows 11
**Цель:** Проверить, что концепция работает end-to-end

### Scope

Включено:
- ✅ Базовая структура Tauri 2 + Next.js 15 + FastAPI
- ✅ Трёхслойный NER pipeline (regex + spaCy + GLiNER + Qwen 7B)
- ✅ EntityRegistry с AES-256-GCM шифрованием
- ✅ Split-screen UI с подсветкой сущностей
- ✅ LLM Panel с выбором Claude/GPT/Gemini
- ✅ WebSocket streaming для ответов LLM
- ✅ Темы (light/dark) и локализация (RU/EN)
- ✅ Один пользователь (single-user mode)
- ✅ Загрузка DOCX/PDF/TXT
- ✅ Все 7 ADR + полная документация

Отложено:
- ❌ Multi-user, RBAC
- ❌ Audit trail
- ❌ База данных (всё в памяти)
- ❌ Интеграция с другими приложениями ЕПАМ
- ❌ Compliance под 152-ФЗ
- ❌ Production deployment

### Definition of Done

- Все 10 task files (`docs/tasks/01-10`) выполнены
- Pipeline даёт recall ≥95% и precision ≥90% на synthetic корпусе
- End-to-end сценарий работает: загрузить → анонимизировать → ревью → отправить в Claude → получить деанонимизированный ответ
- Test coverage backend ≥75%
- Все pre-commit hooks проходят
- Документация обновлена

## v0.2.0-mvp — Workstation Test Build

**Срок:** Месяц 2-3
**Конфигурация:** Intel i9 14900KF, 64GB RAM, RTX 3090, 2TB SSD
**Цель:** Протестировать качество с настоящей моделью (Qwen 32B), все три LLM провайдера, пакетную обработку

### Новое в MVP

- 🎯 **Qwen 2.5 32B** как локальная LLM (качество уровня GPT-4o на русском)
- 🎯 **GLiNER large** вместо medium
- 🎯 **OpenAI Adapter** (GPT-5.4 через Responses API)
- 🎯 **Gemini Adapter** (Gemini 3.1 Pro с thought signatures)
- 🎯 **Diff viewer** для ответов LLM (Monaco DiffEditor)
- 🎯 **History** — список последних сессий с поиском
- 🎯 **Custom dictionaries** — пользователь добавляет специфичные термины
- 🎯 **Batch mode** — обработка нескольких документов подряд
- 🎯 **Export anonymized** — выгрузка обезличенного DOCX/PDF
- 🎯 **Import mapping** — реимпорт mapping table для деанонимизации экспортированного документа
- 🎯 **Performance metrics** — показ времени обработки, статистики использования
- 🎯 **Cost tracking** — суммарная стоимость LLM запросов за период
- 🎯 **Production Dockerfile** для backend
- 🎯 **MVP конфигурация** Docker Compose с tuned параметрами

### Definition of Done

- Все 3 LLM провайдера работают со streaming и thinking
- Qwen 32B показывает заметный прирост качества vs 7B
- Cost tracking точно (±5% от реальных счетов API)
- E2E тесты для основных flows
- Документация обновлена под MVP конфигурацию

## v0.3.0 — Multi-user & Audit

**Срок:** Месяц 4-6
**Конфигурация:** MVP workstation или small server
**Цель:** Подготовка к production: multi-user, audit, начало compliance-фич

### Новое в v0.3.0

- 🔐 **RBAC** с 8 ролями:
  1. Admin — полный доступ
  2. Senior Partner — все сессии своего отдела
  3. Partner — свои сессии + assigned клиенты
  4. Senior Associate — свои сессии
  5. Associate — свои сессии (ограниченный budget)
  6. Paralegal — анонимизация без LLM
  7. Auditor — read-only доступ к audit log
  8. Viewer — только просмотр своих сессий
- 🔐 **SSO интеграция** с Active Directory ЕПАМ
- 🔐 **Append-only audit trail** с hash-chain
- 🔐 **Encrypted disk persistence** для долгих сессий
- 🔐 **PostgreSQL** для метаданных (не для содержимого!)
- 🔐 **Session sharing** — передача сессии другому юристу с правильными правами
- 🔐 **Templates library** — общая библиотека промптов организации
- 🔐 **Performance dashboard** для админов
- 🔐 **Backup integration** — автоматизированные бэкапы БД и конфигов
- 🔐 **Penetration testing** (внешний аудит)
- 🔐 **Security audit** документации и кода

### Definition of Done

- 8 ролей реализованы и протестированы
- Audit log проходит проверку integrity
- SSO работает с тестовым AD
- Penetration test пройден без critical/high issues

## v1.0.0-final — Production Deployment

**Срок:** Месяц 7-12
**Конфигурация:** Серверный кластер в дата-центре ЕПАМ
**Цель:** Боевая эксплуатация всем штатом ЕПАМ

### Аппаратная конфигурация

- 2-4× NVIDIA A100 80GB или H200
- 512 ГБ - 1 ТБ ECC RAM
- NVMe RAID для горячих данных
- Объектное хранилище для бэкапов (S3-совместимое)
- 10 GbE интерконнект
- Резервный кластер (DR)

### Новое в Final

- 🚀 **Kubernetes deployment** с HA, auto-scaling
- 🚀 **Qwen 2.5 72B FP16** или **DeepSeek-V3** или **fine-tuned BERT** на корпусе ЕПАМ
- 🚀 **Multi-tenant** — отделы изолированы
- 🚀 **152-ФЗ compliance** (опционально, конфигурируемо)
- 🚀 **ГОСТ-криптография** (опционально, для ФСТЭК сценариев)
- 🚀 **HashiCorp Vault** для secrets management
- 🚀 **Prometheus + Grafana** monitoring
- 🚀 **Loki** для centralized logging (без PII!)
- 🚀 **PagerDuty** алерты на инциденты
- 🚀 **DR-кластер** в другом дата-центре, репликация
- 🚀 **API доступ** для интеграции с другими приложениями ЕПАМ:
  - **VERITAS** — транскрибированные записи → автоанонимизация → анализ
  - **EPAMOS** — привязка сессий CLEARGATE к делам в CRM
  - **CONCLAVE** — анонимизация subtitles из видеозвонков
- 🚀 **Russian LLM fallback** — YandexGPT, GigaChat как резервные провайдеры на случай блокировок
- 🚀 **Российские embedding модели** для semantic search в истории сессий
- 🚀 **Compliance документация** — DPIA, политики, инструкции
- 🚀 **Training programs** для юристов

### Definition of Done

- Production развёрнут в дата-центре ЕПАМ
- Uptime SLA 99.9% подтверждается мониторингом
- 50+ активных пользователей в день без issues
- Все compliance требования выполнены
- Документация для конечных пользователей переведена и распространена
- Training проведён для всего штата ЕПАМ

## Будущие версии (v2.0+)

Идеи для развития после Final:

### v2.0 — AI-Assisted Legal Workflows

- 🔮 **Шаблонизация типовых задач** — пресеты для конкретных типов договоров, исков, заключений
- 🔮 **Multi-document analysis** — анализ корпуса документов одновременно
- 🔮 **Semantic search** по истории сессий
- 🔮 **Auto-tagging** документов по типам и темам
- 🔮 **Diff между версиями документов** с автоматическим выделением правок
- 🔮 **Citation extraction** — извлечение и проверка ссылок на нормативные акты

### v3.0 — Domain-Specific Models

- 🔮 **Fine-tuned NER** на 5+ лет корпуса ЕПАМ (с согласия клиентов)
- 🔮 **Custom embeddings** для русского юридического языка
- 🔮 **Local fine-tuned LLM** для типовых задач (без отправки в облако вообще)
- 🔮 **Active learning** — система учится на корректировках юристов

### v4.0 — Ecosystem Integration

- 🔮 **Полная интеграция** с VERITAS, EPAMOS, CONCLAVE через единый API gateway
- 🔮 **Публичный API** для клиентов ЕПАМ
- 🔮 **Mobile app** для просмотра ответов LLM на ходу (с ограниченным функционалом)
- 🔮 **Browser extension** для анонимизации текста на любых сайтах

## Ретроспектива и адаптация

После каждой версии — короткая ретроспектива:
1. Что получилось как планировали?
2. Что заняло больше времени, чем ожидалось?
3. Что обнаружилось, чего не было в roadmap?
4. Какие decisions нужно пересмотреть (новые ADR / superseded старые)?

Roadmap — живой документ. Версии и приоритеты могут меняться по мере получения обратной связи от пользователей и появления новых возможностей в LLM экосистеме.
