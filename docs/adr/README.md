# Architecture Decision Records

Этот каталог содержит **Architecture Decision Records (ADR)** для проекта CLEARGATE. Каждый ADR — это короткий документ, фиксирующий важное архитектурное решение, его контекст и последствия.

Формат основан на шаблоне Майкла Найгарда (Michael Nygard, [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

## Зачем нужны ADR

В solo-разработке через вайб-кодинг легко принять решение, забыть его обоснование через месяц и сломать систему случайным изменением. ADR — это «память архитектора», которая позволяет:

- Вернуться через год и понять, почему было выбрано именно это решение
- Не повторять одни и те же дискуссии
- Объяснить решения новым участникам / новым сессиям Claude Code
- Видеть эволюцию архитектуры

## Когда писать ADR

Пиши новый ADR, если решение:
- Меняет архитектуру или влияет на её ключевые свойства (производительность, безопасность, масштабируемость)
- Выбирает между двумя+ серьёзными альтернативами
- Будет дорого изменить позже
- Должно быть объяснимо для будущих сессий Claude Code

**Не пиши ADR** для тривиальных решений (имена переменных, форматирование, выбор между двумя эквивалентными библиотеками).

## Список ADR

| № | Название | Статус |
|---|----------|--------|
| [0001](0001-use-tauri-over-electron.md) | Use Tauri 2 over Electron for desktop shell | Accepted |
| [0002](0002-three-layer-ner-pipeline.md) | Three-layer NER pipeline (regex + NER + LLM) | Accepted |
| [0003](0003-presidio-as-orchestrator.md) | Microsoft Presidio as anonymization orchestrator | Accepted |
| [0004](0004-ollama-for-local-llm.md) | Ollama for local LLM inference | Accepted |
| [0005](0005-entity-registry-design.md) | EntityRegistry with consistent placeholder mapping | Accepted |
| [0006](0006-native-llm-adapters-over-unified-shim.md) | Native LLM SDKs over unified shim | Accepted |
| [0007](0007-aes-256-gcm-for-mapping-table.md) | AES-256-GCM for mapping table encryption | Accepted |

## Шаблон нового ADR

Скопируй блок ниже в новый файл `NNNN-короткое-название.md` (NNNN — следующий номер с ведущими нулями):

```markdown
# ADR-NNNN: Заголовок решения

**Дата:** YYYY-MM-DD
**Статус:** Proposed | Accepted | Deprecated | Superseded by ADR-XXXX
**Авторы:** Имя

## Контекст

Какую проблему мы решаем? Какие силы действуют (бизнес, технические, организационные)?
Что мы знали и предполагали на момент принятия решения?

## Решение

Что мы решили сделать. Конкретно и однозначно.

## Альтернативы, которые рассматривались

1. **Альтернатива А** — почему отвергнута
2. **Альтернатива Б** — почему отвергнута

## Последствия

### Положительные
- ...

### Отрицательные / компромиссы
- ...

### Нейтральные
- ...

## Связанные ADR

- ADR-XXXX (если есть)

## Ссылки

- Документация / источники / бенчмарки
```

## Статусы ADR

- **Proposed** — предложено, ещё не принято
- **Accepted** — принято и реализовано (или в процессе)
- **Deprecated** — устарело, но не заменено
- **Superseded by ADR-XXXX** — заменено новым решением

ADR никогда не редактируются после принятия. Если решение меняется — создаётся новый ADR с пометкой `Superseded by` в старом.
