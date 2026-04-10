"""Tests for AES-256-GCM crypto service."""

import secrets

import pytest
from cryptography.exceptions import InvalidTag

from app.services.crypto import CryptoService


@pytest.fixture()
def master_key():
    return secrets.token_bytes(32)


@pytest.fixture()
def crypto(master_key):
    return CryptoService(master_key)


class TestCryptoService:
    def test_init_valid_key(self, master_key):
        service = CryptoService(master_key)
        assert service is not None

    def test_init_invalid_key_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            CryptoService(b"short")

    def test_encrypt_decrypt_roundtrip(self, crypto):
        data = {"key": "value", "nested": {"a": 1}}
        blob = crypto.encrypt_mapping(data, "session-1")
        result = crypto.decrypt_mapping(blob, "session-1")
        assert result == data

    def test_encrypt_decrypt_unicode(self, crypto):
        data = {"name": "Иванов Иван Иванович", "type": "ЛИЦО"}
        blob = crypto.encrypt_mapping(data, "session-1")
        result = crypto.decrypt_mapping(blob, "session-1")
        assert result == data

    def test_wrong_session_id_fails(self, crypto):
        data = {"key": "value"}
        blob = crypto.encrypt_mapping(data, "session-1")
        with pytest.raises(InvalidTag):
            crypto.decrypt_mapping(blob, "wrong-session")

    def test_wrong_master_key_fails(self, master_key):
        crypto1 = CryptoService(master_key)
        crypto2 = CryptoService(secrets.token_bytes(32))
        data = {"key": "value"}
        blob = crypto1.encrypt_mapping(data, "session-1")
        with pytest.raises(InvalidTag):
            crypto2.decrypt_mapping(blob, "session-1")

    def test_tampered_ciphertext_fails(self, crypto):
        data = {"key": "value"}
        blob = crypto.encrypt_mapping(data, "session-1")
        tampered = blob[:-1] + bytes([(blob[-1] + 1) % 256])
        with pytest.raises(InvalidTag):
            crypto.decrypt_mapping(tampered, "session-1")

    def test_blob_too_short(self, crypto):
        with pytest.raises(ValueError, match="too short"):
            crypto.decrypt_mapping(b"short", "session-1")

    def test_derive_session_key_deterministic(self, crypto):
        key1 = crypto.derive_session_key("session-1")
        key2 = crypto.derive_session_key("session-1")
        assert key1 == key2

    def test_different_sessions_different_keys(self, crypto):
        key1 = crypto.derive_session_key("session-1")
        key2 = crypto.derive_session_key("session-2")
        assert key1 != key2
