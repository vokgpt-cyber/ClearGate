# ADR-0007: AES-256-GCM for mapping table encryption

**Дата:** 2026-04-09
**Статус:** Accepted
**Авторы:** EPAM Legal Dev

## Контекст

Mapping table — это таблица соответствий между реальными данными (ФИО, ИНН, суммы) и плейсхолдерами (`[ЛИЦО_1]`, `[ИНН_1]`, ...). Это **самые чувствительные данные** во всей системе VELUM: тот, кто получит mapping и анонимизированный текст, может полностью восстановить оригинальный документ.

Требования к шифрованию:
- **Сильный алгоритм** с authenticated encryption (защита от tampering)
- **Не требует** особых аппаратных ускорителей (работает на любом CPU)
- **Стандартизованный** — не cargo-cult криптография
- **Поддерживается** в стандартных Python библиотеках без экзотических зависимостей
- **Опционально** возможность замены на ГОСТ для сценариев ФСТЭК (Final v3.0)

## Решение

Использовать **AES-256-GCM** для шифрования mapping table с такой схемой ключей:

1. **Master key** — 256-битный ключ, генерируется при первой инициализации, хранится в `.env` (для Alpha) или secret manager (для Final). НЕ коммитится в git.
2. **Session key** — производный 256-битный ключ, генерируется на каждую сессию через **HKDF-SHA256** от master key + session UUID + nonce
3. **Nonce** — 96-битный, генерируется случайно для каждой операции шифрования (требование GCM)

Реализация через `cryptography` библиотеку (стандарт de facto в Python для криптографии).

## Альтернативы, которые рассматривались

### AES-256-CBC + HMAC-SHA256 (Encrypt-then-MAC)
- ✅ Классика
- ❌ Сложнее правильно реализовать (риск oracle padding атак если HMAC проверяется некорректно)
- ❌ Два примитива вместо одного → больше места для ошибок

### ChaCha20-Poly1305
- ✅ Authenticated encryption из коробки
- ✅ Быстрее AES на устройствах без AES-NI
- ✅ Современный, рекомендуется в TLS 1.3
- ⚠️ AES-NI есть на всех современных x86 CPU → AES-GCM в реальности быстрее
- 🔄 Могло бы быть равноценной альтернативой, но AES-GCM привычнее, имеет больше документации и audit'ов

### NaCl SecretBox (libsodium)
- ✅ Очень простой API, сложно использовать неправильно
- ✅ ChaCha20-Poly1305 под капотом
- ⚠️ Дополнительная зависимость (`pynacl`) — но мы её и так используем для `sodium_memzero`
- 🔄 Использовать **в дополнение** к AES-GCM для очистки памяти, не вместо

### ГОСТ Р 34.12-2015 (Кузнечик)
- ✅ Соответствие требованиям ФСТЭК для российских госструктур
- ❌ Меньше open-source реализаций, риск багов
- ❌ Не нужен на этапе Alpha (внутренний exploration tool)
- 🔄 Запланирован для **опциональной** поддержки в Final v3.0

### Пользовательский password + Argon2id
- ✅ Не нужен master key в .env
- ❌ Юрист должен помнить пароль для каждой сессии — UX страдает
- 🔄 Можно добавить как опцию в v2.0 для сценариев high-security

## Решение в деталях

### Генерация master key
```python
import secrets
import base64

# Однократно при установке
master_key = secrets.token_bytes(32)  # 256 бит
print(base64.b64encode(master_key).decode())
# Сохранить в .env как VELUM_MASTER_KEY
```

### Шифрование mapping table
```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import secrets
import json

class CryptoService:
    def __init__(self, master_key: bytes) -> None:
        self.master_key = master_key

    def derive_session_key(self, session_id: str) -> bytes:
        """Derive a per-session key from master key using HKDF."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session_id.encode(),
            info=b"velum-mapping-table-v1",
        )
        return hkdf.derive(self.master_key)

    def encrypt_mapping(self, mapping: dict, session_id: str) -> bytes:
        """Encrypt mapping table for a session."""
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce = secrets.token_bytes(12)  # 96 бит для GCM
        plaintext = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ciphertext  # nonce префиксом для удобства

    def decrypt_mapping(self, blob: bytes, session_id: str) -> dict:
        """Decrypt mapping table for a session."""
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce, ciphertext = blob[:12], blob[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))
```

### Защита памяти
- Master key загружается один раз и хранится в защищённой памяти процесса
- При генерации session key используется `mlock()` (через `pynacl.utils.sodium_mlock()`) на буфер с ключом
- При очистке сессии — `sodium_memzero` на все буферы с ключами и mapping

### Хранение
- **In-memory only** для большинства сценариев
- **Опциональный disk cache** — зашифрованный blob сохраняется в `~/.velum/sessions/<uuid>.blob` с TTL (по умолчанию 24 часа)
- TTL enforced через scheduled task, при истечении файл удаляется и перезаписывается случайными байтами

## Последствия

### Положительные
- Стандартизованный, well-audited алгоритм
- AES-NI ускорение на любом современном CPU
- HKDF от master key даёт уникальные ключи на сессию (forward secrecy между сессиями)
- Authenticated encryption защищает от tampering
- Простой API через `cryptography` library

### Отрицательные / компромиссы
- Master key в `.env` — слабое место в Alpha. В Final нужен secret manager.
- Если master key утерян — все mapping table нерасшифровываемы (это by design, но требует правильного backup master key отдельно от data backups)
- 12-байтовый nonce GCM имеет ограничение на количество шифрований одним ключом (~2^32 операций) — для нашего сценария (одна mapping table на сессию) это не проблема, но важно помнить

### Нейтральные
- Зависимость от `cryptography` (стандарт de facto в Python)
- Ключи в env vars — нужна осторожность с переменными окружения в Docker/Kubernetes

## Хранение master key — best practices

| Окружение | Где хранить master key |
|-----------|------------------------|
| Alpha (dev) | `.env` файл (в gitignore), backed up отдельно от data backups |
| MVP (тест) | Windows Credential Manager или encrypted file с паролем |
| Final (prod) | HashiCorp Vault, AWS Secrets Manager, или российский аналог; ротация по расписанию |

## Связанные ADR

- [ADR-0005](0005-entity-registry-design.md) — что именно мы шифруем

## Ссылки

- [cryptography library docs](https://cryptography.io/en/latest/)
- [AES-GCM RFC 5288](https://datatracker.ietf.org/doc/html/rfc5288)
- [HKDF RFC 5869](https://datatracker.ietf.org/doc/html/rfc5869)
- [NIST SP 800-38D (GCM)](https://csrc.nist.gov/publications/detail/sp/800-38d/final)
