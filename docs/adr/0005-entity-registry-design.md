# ADR-0005: EntityRegistry with consistent placeholder mapping

**Дата:** 2026-04-09
**Статус:** Accepted
**Авторы:** EPAM Legal Dev

## Контекст

Для качественной работы LLM-консультирования критически важно, чтобы одна и та же реальная сущность всегда заменялась одним и тем же плейсхолдером. Если «Иван Петров» в одном месте становится `[ЛИЦО_1]`, а в другом — `[ЛИЦО_5]`, LLM не поймёт, что речь об одном человеке, и качество анализа резко упадёт.

В русском языке эта задача усложняется морфологией:
- «Иван Петров» (именительный) = «Ивана Петрова» (родительный) = «Ивану Петрову» (дательный)
- «Иванов И.И.» = «Иванов Иван Иванович» = «И.И. Иванов»
- «ООО „Ромашка"» = «Ромашка» = «общество с ограниченной ответственностью „Ромашка"»

Дополнительно нужно:
- Безопасное хранение mapping table (это самые чувствительные данные системы — соответствие плейсхолдеров реальным значениям)
- Мерджинг сущностей из трёх слоёв NER pipeline без дублирования
- Поддержка ручного редактирования (юрист может скорректировать сущность в UI)
- Возможность экспорта зашифрованного маппинга для режима «только анонимизация»

## Решение

Создать класс `EntityRegistry` с такими свойствами:

1. **In-memory storage** с AES-256-GCM шифрованием при сериализации
2. **Нормализация** русских имён через pymorphy3 + правила Natasha
3. **Нечёткое сопоставление** через расстояние Левенштейна для близких форм
4. **Инкрементальная нумерация** плейсхолдеров по типу: `[ЛИЦО_1]`, `[ЛИЦО_2]`, `[ОРГАНИЗАЦИЯ_1]`, ...
5. **Bidirectional mapping**: оригинал → placeholder для анонимизации, placeholder → оригинал для деанонимизации
6. **Защита памяти** через `mlock()` (Unix) / `VirtualLock()` (Windows)
7. **Очистка** через `sodium_memzero` при закрытии сессии

## API

```python
class EntityRegistry:
    """In-memory registry mapping real entities to anonymized placeholders.

    Thread-safe. All sensitive data is encrypted at rest with AES-256-GCM.
    Memory pages are locked to prevent swap.
    """

    def __init__(self, master_key: bytes, locale: Literal["ru", "en"] = "ru") -> None: ...

    def get_or_create_placeholder(self, entity: Entity) -> str:
        """Get existing placeholder for entity, or create a new one.

        Performs normalization (pymorphy3 for Russian) and fuzzy matching
        (Levenshtein) to find existing entries for inflected forms.
        """

    def deanonymize(self, text: str) -> str:
        """Replace all placeholders in text with original values."""

    def update_entity(self, placeholder: str, new_value: str) -> None:
        """User-driven correction during review."""

    def export_encrypted(self) -> bytes:
        """Serialize and encrypt mapping table for disk persistence."""

    @classmethod
    def import_encrypted(cls, blob: bytes, master_key: bytes) -> "EntityRegistry":
        """Restore registry from encrypted blob."""

    def clear(self) -> None:
        """Securely zero out all sensitive data."""
```

## Алгоритм нормализации (русский язык)

```
1. Lower case
2. Strip пунктуации и лишних пробелов
3. Если это имя (тип PER):
   a. Распарсить через Natasha NamesExtractor
   b. Привести каждый компонент к именительному падежу через pymorphy3
   c. Канонизировать порядок: [Фамилия, Имя, Отчество]
4. Если это организация (тип ORG):
   a. Удалить юридическую форму (ООО, АО, ЗАО, OOO, JSC, ...)
   b. Привести к именительному падежу
5. Если это адрес (тип LOC/ADDR):
   a. Нормализовать через Natasha AddressExtractor
6. Вернуть нормализованную строку как ключ для поиска
```

## Алгоритм нечёткого сопоставления

```
1. Точный поиск нормализованной формы в registry
2. Если не найдено:
   a. Для имён: проверить аббревиатурные варианты (Иванов И.И. ↔ Иванов Иван Иванович)
   b. Для всех типов: Levenshtein distance ≤ 2 для коротких строк, ≤ 4 для длинных
3. Если найдено совпадение с confidence > 0.85 — вернуть существующий placeholder
4. Иначе создать новый placeholder
```

## Шифрование (см. также ADR-0007)

Mapping table сериализуется в JSON, потом шифруется AES-256-GCM с сессионным ключом, производным от мастер-ключа через HKDF-SHA256.

## Альтернативы, которые рассматривались

### Plain dict без шифрования
- ✅ Простота
- ❌ В памяти лежит таблица соответствий — самые чувствительные данные системы. Любой дамп памяти их раскрывает.
- ❌ Не соответствует privacy-by-design

### SQLite в файле
- ✅ Простой persistence
- ❌ Файл на диске — лишний риск утечки
- ❌ Не нужен в большинстве сценариев (mapping живёт только в рамках сессии)

### Redis
- ✅ Подходит для распределённой архитектуры
- ❌ Overkill для single-user Alpha/MVP
- ❌ Дополнительный сервис → лишняя attack surface
- 🔄 Возможно для Final v3.0 в кластерном режиме

## Последствия

### Положительные
- Корректный маппинг даже для сложных русских падежей и аббревиатур
- Защита самых чувствительных данных в памяти
- API прост для использования из NER pipeline и роутеров FastAPI
- Опциональный export в зашифрованный blob позволяет реализовать режим «только анонимизация» (юрист экспортирует mapping, работает с анонимным документом отдельно, импортирует mapping для деанонимизации)

### Отрицательные / компромиссы
- pymorphy3 + Levenshtein добавляют ~50ms на сущность → для документа на 100 сущностей это +5 секунд. Можно оптимизировать кэшированием нормализованных форм.
- Сложность отладки нечёткого сопоставления — иногда нужно понять, почему две формы не были связаны
- mlock() требует прав / может не работать в Docker без `--cap-add=IPC_LOCK`

### Нейтральные
- Дополнительная зависимость pymorphy3 — но она нужна и для других модулей

## Тестирование

Регрессионный test set с примерами:
- Все падежи имён: `Иван Петров`, `Ивана Петрова`, `Ивану Петрову`, ...
- Аббревиатуры: `Иванов И.И.` ↔ `Иванов Иван Иванович`
- Организации: `ООО "Ромашка"`, `Ромашка`, `общество "Ромашка"`
- Опечатки: `Иванов` vs `Ивaнов` (с латинской `a`)
- Edge cases: однофамильцы (`Петров А.А.` и `Петров Б.Б.` — разные сущности!)

## Связанные ADR

- [ADR-0002](0002-three-layer-ner-pipeline.md) — pipeline, который заполняет registry
- [ADR-0007](0007-aes-256-gcm-for-mapping-table.md) — детали шифрования

## Ссылки

- [pymorphy3 documentation](https://pymorphy2.readthedocs.io/) (актуальная для pymorphy3)
- [Natasha NamesExtractor](https://github.com/natasha/natasha#namesextractor)
