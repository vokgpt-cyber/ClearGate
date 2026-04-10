# VELUM

> Завеса, за которой — адвокатская тайна.

**VELUM** — on-premise приложение для юристов АБ ЕПАМ, обеспечивающее безопасную работу с топовыми LLM мира (Claude, GPT, Gemini) через автоматическую анонимизацию и деанонимизацию чувствительных данных. Часть экосистемы ЕПАМ (VERITAS, EPAMOS, CONCLAVE, VELUM).

---

## Зачем

Юридическая индустрия стоит перед парадоксом: LLM радикально повышают производительность, но профессиональная этика и адвокатская тайна запрещают отправлять клиентские данные в облако. VELUM разрешает этот парадокс через техническое решение: чувствительные данные никогда не покидают периметр ЕПАМ. Облачные LLM получают только обезличенный текст с нейтральными плейсхолдерами, а юрист видит ответ с автоматически восстановленными реальными данными.

## Как это работает

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Документ       │    │  VELUM           │    │  Cloud LLM      │
│  с реальными    │───▶│  (on-premise)    │───▶│  Claude/GPT/    │
│  данными        │    │                  │    │  Gemini         │
└─────────────────┘    │  • NER pipeline  │    └─────────────────┘
                       │  • Mapping table │             │
                       │  • Шифрование    │             │
                       └──────────────────┘             │
                                ▲                       │
                                │                       │
                                └───────────────────────┘
                                  Деанонимизация ответа
```

**Трёхслойный pipeline анонимизации:**
1. **Regex** (Microsoft Presidio) — структурированные данные: ИНН, ОГРН, СНИЛС, паспорта РФ
2. **NER** (spaCy ru_core_news_lg + GLiNER) — ФИО, организации, адреса
3. **Local LLM** (Ollama Qwen 2.5) — сложные случаи и кореференция

## Технологический стек

| Слой | Технология |
|------|------------|
| Desktop shell | Tauri 2.10 |
| Frontend | Next.js 15 + React 19 + TypeScript 5 + Tailwind CSS 4 |
| Backend | Python 3.12 + FastAPI 0.116 + Pydantic v2 |
| ML pipeline | Microsoft Presidio + spaCy + GLiNER + Natasha/Yargy |
| Local LLM | Ollama + Qwen 2.5 (7B/32B/72B по конфигурации) |
| Cloud LLM | Anthropic Claude, OpenAI GPT, Google Gemini (нативные SDK) |
| Шифрование | AES-256-GCM |
| Развёртывание | Docker Compose / Kubernetes |

## Три конфигурации развёртывания

| | **Alpha** | **MVP** | **Final** |
|---|---|---|---|
| Назначение | Разработка | Тестирование | Боевая эксплуатация |
| GPU | RTX 4060 (8 ГБ) | RTX 3090 (24 ГБ) | 2–4× A100/H200 |
| Локальная LLM | Qwen 7B Q4 | Qwen 32B Q4 | Qwen 72B FP16 |
| Параллельных пользователей | 1 | 1–3 | 50–200+ |

Подробнее: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

## Быстрый старт (Alpha)

**Требования:**
- Windows 11 / macOS / Linux
- Docker Desktop с поддержкой NVIDIA GPU
- Python 3.12+
- Node.js 20+
- Rust (для Tauri)
- Git

**Установка:**
```powershell
# 1. Клонировать (или распаковать архив)
cd D:\Projects
git init velum && cd velum

# 2. Развернуть структуру (см. INSTALL.md)
.\scripts\setup-dev.ps1

# 3. Загрузить ML модели
.\scripts\download-models.ps1 -Profile alpha

# 4. Настроить API ключи
copy .env.example .env
notepad .env  # Вписать ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY

# 5. Запустить
docker compose up -d
```

Приложение откроется на `http://localhost:3000`.

Полная инструкция: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)

## Документация

- 🏗 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — архитектура системы
- 🚀 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — развёртывание Alpha/MVP/Final
- 💻 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — настройка dev окружения
- 🧪 [`docs/TESTING.md`](docs/TESTING.md) — стратегия тестирования
- 🔒 [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) — модель угроз
- 📋 [`docs/ROADMAP.md`](docs/ROADMAP.md) — план развития
- 🧠 [`docs/adr/`](docs/adr/) — Architecture Decision Records
- 📝 [`docs/tasks/`](docs/tasks/) — задачи разработки

## Безопасность

VELUM спроектирован по принципу **privacy by design**:
- Анонимизация выполняется **только локально**, на серверах ЕПАМ
- Mapping table хранится **в памяти** с AES-256-GCM шифрованием, никогда не пишется на диск без явной команды пользователя
- Логи **никогда** не содержат оригинальных данных, mapping table или ключей
- Облачные LLM получают **только** обезличенный текст с плейсхолдерами

При обнаружении уязвимости — см. [`SECURITY.md`](SECURITY.md).

## Лицензия

Внутренняя разработка АБ ЕПАМ. Все права защищены.

## Версия

Текущая версия: **0.1.0-alpha** (см. [`CHANGELOG.md`](CHANGELOG.md))
