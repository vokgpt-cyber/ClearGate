# Task 04: EntityRegistry with Encryption and Russian Normalization

## Контекст

NER pipeline (Task 03) находит сущности. EntityRegistry — это компонент, который:
1. Назначает каждой уникальной сущности консистентный плейсхолдер (`[ЛИЦО_1]`, `[ОРГАНИЗАЦИЯ_1]`)
2. Учитывает русскую морфологию (Иван Петров = Ивана Петрова = Ивану Петрову)
3. Хранит mapping table в памяти под AES-256-GCM шифрованием
4. Поддерживает экспорт/импорт зашифрованного mapping для режима «только анонимизация»

## Зависимости

- Task 02 (regex recognizers — для типов сущностей)
- Task 03 (NER pipeline — даёт DetectedEntity)
- Прочитать `docs/adr/0005-entity-registry-design.md`
- Прочитать `docs/adr/0007-aes-256-gcm-for-mapping-table.md`

## Цель

Создать класс `EntityRegistry`, который полностью реализует требования из ADR-0005.

## Требования

### API

```python
# backend/app/services/entity_registry.py

from typing import Literal
from pydantic import BaseModel
from app.services.crypto import CryptoService
from app.models.entities import DetectedEntity, EntityType


class MappingEntry(BaseModel):
    placeholder: str        # "[ЛИЦО_1]"
    canonical_value: str    # нормализованная форма
    original_forms: list[str]  # все встреченные варианты
    entity_type: EntityType


class EntityRegistry:
    """In-memory registry mapping real entities to anonymized placeholders.

    Provides consistent placeholder assignment with Russian morphological
    awareness. Mapping table is encrypted with AES-256-GCM at rest.

    Thread-safety: NOT thread-safe by design (one registry per session).
    """

    def __init__(
        self,
        master_key: bytes,
        session_id: str,
        locale: Literal["ru", "en"] = "ru",
    ) -> None:
        self.session_id = session_id
        self.locale = locale
        self._crypto = CryptoService(master_key)
        self._counters: dict[EntityType, int] = {}
        self._mapping: dict[str, MappingEntry] = {}  # canonical → entry
        self._reverse: dict[str, MappingEntry] = {}  # placeholder → entry
        self._normalizer = self._build_normalizer(locale)

    def get_or_create_placeholder(self, entity: DetectedEntity) -> str:
        """Get existing placeholder or create a new one for an entity.

        Performs normalization (pymorphy3 for Russian) and fuzzy matching
        (Levenshtein) to find existing entries for inflected forms.
        """
        canonical = self._normalize(entity.text, entity.entity_type)

        # Точное совпадение
        if canonical in self._mapping:
            entry = self._mapping[canonical]
            if entity.text not in entry.original_forms:
                entry.original_forms.append(entity.text)
            return entry.placeholder

        # Нечёткое совпадение
        fuzzy_match = self._fuzzy_lookup(canonical, entity.entity_type)
        if fuzzy_match:
            fuzzy_match.original_forms.append(entity.text)
            return fuzzy_match.placeholder

        # Новая сущность
        return self._create_new_entry(entity, canonical)

    def anonymize_text(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> str:
        """Replace all entity occurrences with placeholders."""
        # Сортируем по позиции в обратном порядке для безопасной замены
        sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
        result = text
        for entity in sorted_entities:
            placeholder = self.get_or_create_placeholder(entity)
            result = result[:entity.start] + placeholder + result[entity.end:]
        return result

    def deanonymize_text(self, text: str) -> str:
        """Replace all placeholders in text with original (canonical) values."""
        result = text
        for placeholder, entry in self._reverse.items():
            # Используем canonical_value (нормализованную форму) для замены
            # Юрист может видеть, что данные восстановлены
            result = result.replace(placeholder, entry.canonical_value)
        return result

    def update_entity(self, placeholder: str, new_canonical: str) -> None:
        """User-driven correction during review."""
        if placeholder not in self._reverse:
            raise KeyError(f"Placeholder {placeholder} not in registry")
        entry = self._reverse[placeholder]
        old_canonical = entry.canonical_value
        entry.canonical_value = new_canonical
        # Перепривязываем в _mapping
        del self._mapping[old_canonical]
        self._mapping[new_canonical] = entry

    def export_encrypted(self) -> bytes:
        """Serialize mapping table and encrypt with AES-256-GCM."""
        data = {
            "session_id": self.session_id,
            "locale": self.locale,
            "counters": self._counters,
            "entries": [e.model_dump() for e in self._mapping.values()],
        }
        return self._crypto.encrypt_mapping(data, self.session_id)

    @classmethod
    def import_encrypted(cls, blob: bytes, master_key: bytes) -> "EntityRegistry":
        """Restore registry from encrypted blob."""
        crypto = CryptoService(master_key)
        # session_id извлекается из первых байт после расшифровки
        # Сначала пробуем расшифровать с временным session_id из заголовка blob
        # ... (реализация зависит от формата blob)
        ...

    def clear(self) -> None:
        """Securely zero out all sensitive data."""
        # Используем sodium_memzero на буферах если возможно
        for entry in self._mapping.values():
            entry.canonical_value = "\x00" * len(entry.canonical_value)
            entry.original_forms = []
        self._mapping.clear()
        self._reverse.clear()
        self._counters.clear()

    def __del__(self) -> None:
        self.clear()

    # Внутренние методы

    def _normalize(self, text: str, entity_type: EntityType) -> str:
        """Normalize entity text for canonical lookup."""
        return self._normalizer.normalize(text, entity_type)

    def _fuzzy_lookup(
        self, canonical: str, entity_type: EntityType
    ) -> MappingEntry | None:
        """Find similar existing entry using Levenshtein and type-specific rules."""
        from Levenshtein import distance

        max_dist = 2 if len(canonical) < 20 else 4
        candidates = [
            entry for entry in self._mapping.values()
            if entry.entity_type == entity_type
        ]
        for entry in candidates:
            if distance(canonical, entry.canonical_value) <= max_dist:
                return entry
            # Дополнительные правила для имён
            if entity_type == "PER" and self._names_match(canonical, entry.canonical_value):
                return entry
        return None

    def _names_match(self, name1: str, name2: str) -> bool:
        """Check if two normalized names refer to the same person.

        Handles cases like "Иванов И.И." == "Иванов Иван Иванович"
        """
        ...

    def _create_new_entry(
        self, entity: DetectedEntity, canonical: str
    ) -> str:
        """Create new mapping entry and return its placeholder."""
        counter = self._counters.get(entity.entity_type, 0) + 1
        self._counters[entity.entity_type] = counter

        type_label = self._type_label(entity.entity_type, self.locale)
        placeholder = f"[{type_label}_{counter}]"

        entry = MappingEntry(
            placeholder=placeholder,
            canonical_value=canonical,
            original_forms=[entity.text],
            entity_type=entity.entity_type,
        )
        self._mapping[canonical] = entry
        self._reverse[placeholder] = entry
        return placeholder

    def _type_label(self, entity_type: EntityType, locale: str) -> str:
        """Map entity type to human-readable label."""
        if locale == "ru":
            labels = {
                "PER": "ЛИЦО",
                "ORG": "ОРГАНИЗАЦИЯ",
                "LOC": "МЕСТО",
                "ADDR": "АДРЕС",
                "MON": "СУММА",
                "DATE": "ДАТА",
                "RU_INN": "ИНН",
                "RU_OGRN": "ОГРН",
                "RU_SNILS": "СНИЛС",
                "RU_PASSPORT": "ПАСПОРТ",
                "RU_BANK_ACCOUNT": "СЧЁТ",
                "PHONE": "ТЕЛЕФОН",
                "EMAIL": "EMAIL",
                "CASE_NUMBER": "ДЕЛО",
                "POSITION": "ДОЛЖНОСТЬ",
                "PROJECT_CODENAME": "ПРОЕКТ",
            }
        else:
            labels = {
                "PER": "PERSON",
                "ORG": "ORG",
                # ...
            }
        return labels.get(entity_type, entity_type)

    def _build_normalizer(self, locale: str) -> "EntityNormalizer":
        from app.services.entity_normalizer import RussianEntityNormalizer, EnglishEntityNormalizer
        return RussianEntityNormalizer() if locale == "ru" else EnglishEntityNormalizer()
```

### Crypto service

```python
# backend/app/services/crypto.py

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import secrets
import json


class CryptoService:
    """AES-256-GCM encryption for mapping tables."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("Master key must be 32 bytes (256 bits)")
        self.master_key = master_key

    def derive_session_key(self, session_id: str) -> bytes:
        """Derive a per-session key from master key using HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session_id.encode("utf-8"),
            info=b"cleargate-mapping-table-v1",
        )
        return hkdf.derive(self.master_key)

    def encrypt_mapping(self, data: dict, session_id: str) -> bytes:
        """Encrypt a mapping dict, return: nonce (12 bytes) + ciphertext."""
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ciphertext

    def decrypt_mapping(self, blob: bytes, session_id: str) -> dict:
        """Decrypt a mapping blob (nonce + ciphertext)."""
        if len(blob) < 13:
            raise ValueError("Blob too short")
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce, ciphertext = blob[:12], blob[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))
```

### Russian entity normalizer

```python
# backend/app/services/entity_normalizer.py

import pymorphy3
from natasha import NamesExtractor, MorphVocab
from app.models.entities import EntityType


class RussianEntityNormalizer:
    """Normalize Russian entities to canonical form for matching."""

    def __init__(self) -> None:
        self.morph = pymorphy3.MorphAnalyzer()
        self.morph_vocab = MorphVocab()
        self.names_extractor = NamesExtractor(self.morph_vocab)

    def normalize(self, text: str, entity_type: EntityType) -> str:
        text = text.strip().lower()
        if entity_type == "PER":
            return self._normalize_person(text)
        elif entity_type == "ORG":
            return self._normalize_org(text)
        elif entity_type == "ADDR":
            return self._normalize_address(text)
        else:
            return text

    def _normalize_person(self, text: str) -> str:
        """Normalize person name using Natasha + pymorphy3."""
        # Парсим имя через Natasha
        matches = list(self.names_extractor(text))
        if matches:
            name = matches[0].fact
            parts = []
            if name.last:
                parts.append(self._lemmatize(name.last))
            if name.first:
                parts.append(self._lemmatize(name.first))
            if name.middle:
                parts.append(self._lemmatize(name.middle))
            return " ".join(parts)
        # Fallback: лемматизация по словам
        words = text.split()
        return " ".join(self._lemmatize(w) for w in words)

    def _normalize_org(self, text: str) -> str:
        """Remove legal forms (ООО, АО, ...) and normalize."""
        legal_forms = [
            "общество с ограниченной ответственностью",
            "ооо", "оао", "зао", "пао", "ао",
            "акционерное общество", "публичное акционерное общество",
        ]
        result = text
        for form in legal_forms:
            result = result.replace(form, "").strip()
        # Удалить кавычки
        result = result.strip("«»\"'")
        return result

    def _normalize_address(self, text: str) -> str:
        # MVP: просто lowercase + убрать лишние пробелы
        return " ".join(text.split())

    def _lemmatize(self, word: str) -> str:
        return self.morph.parse(word)[0].normal_form
```

## Файлы для создания

```
backend/app/services/entity_registry.py
backend/app/services/crypto.py
backend/app/services/entity_normalizer.py
backend/app/models/entities.py     # MappingEntry, DetectedEntity, EntityType
backend/tests/services/test_entity_registry.py
backend/tests/services/test_crypto.py
backend/tests/services/test_entity_normalizer.py
```

## Тесты

### test_entity_registry.py
- Базовая операция: добавить сущность → получить placeholder
- Консистентность: одна и та же сущность → один и тот же placeholder
- Морфология: «Иван Петров» и «Ивана Петрова» → один placeholder
- Аббревиатуры: «Иванов И.И.» и «Иванов Иван Иванович» → один placeholder
- Разные сущности одного типа: «Иван Петров» и «Анна Сидорова» → разные placeholders
- Опечатки в пределах Левенштейн ≤ 2 → один placeholder
- Опечатки больше Левенштейн ≤ 2 → разные placeholders
- Edge: однофамильцы (`Петров А.А.` и `Петров Б.Б.`) → разные placeholders
- Round-trip: anonymize → deanonymize возвращает исходный текст
- Export/import encrypted blob

### test_crypto.py
- Шифрование → расшифровка возвращает оригинал
- Неправильный master key → DecryptionError
- Неправильный session_id → DecryptionError
- Tampered ciphertext → DecryptionError
- Master key неправильной длины → ValueError при init

### test_entity_normalizer.py
- Имена в разных падежах → одна каноническая форма
- ООО «Ромашка» → ромашка
- Сложные имена с отчествами

## Acceptance Criteria

- [ ] Все классы реализованы согласно API
- [ ] Тесты покрывают все edge cases из ADR-0005
- [ ] Round-trip тест (anonymize → deanonymize) проходит
- [ ] Encryption тесты проходят
- [ ] Test coverage ≥ 90% для core логики
- [ ] mypy strict без ошибок
- [ ] ruff без warnings
- [ ] Документация: docstring для каждого публичного метода с примерами

## Команды для запуска

```powershell
cd backend
pytest tests/services/test_entity_registry.py -v
pytest tests/services/test_crypto.py -v
pytest tests/services/test_entity_normalizer.py -v
pytest --cov=app.services.entity_registry --cov=app.services.crypto --cov-report=term-missing
```

## Коммит

```
feat(backend): implement EntityRegistry with AES-256-GCM encryption

- Consistent placeholder assignment with Russian morphological awareness
- pymorphy3-based normalization for declensions
- Levenshtein-based fuzzy matching for typos
- Special handling for abbreviated names ("Иванов И.И." == "Иванов Иван Иванович")
- AES-256-GCM encryption with HKDF-derived session keys
- Export/import of encrypted mapping blobs for "anonymize-only" mode
- Secure memory cleanup on session close

Closes task #4
```
