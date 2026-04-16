"""AES-256-GCM encryption service for mapping tables.

Uses HKDF-SHA256 to derive per-session keys from a master key,
then encrypts/decrypts JSON data with AES-256-GCM (96-bit nonce).
"""

from __future__ import annotations

import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_SIZE = 12  # 96-bit nonce per NIST SP 800-38D
_KEY_SIZE = 32  # 256-bit key
_HKDF_INFO = b"cleargate-mapping-table-v1"


class CryptoService:
    """AES-256-GCM encryption for mapping tables.

    Args:
        master_key: 32-byte (256-bit) master key.

    Raises:
        ValueError: If master_key is not exactly 32 bytes.

    Examples:
        >>> crypto = CryptoService(secrets.token_bytes(32))
        >>> blob = crypto.encrypt_mapping({"key": "value"}, "session-123")
        >>> data = crypto.decrypt_mapping(blob, "session-123")
    """

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != _KEY_SIZE:
            raise ValueError(f"Master key must be {_KEY_SIZE} bytes ({_KEY_SIZE * 8} bits)")
        self._master_key = master_key

    def derive_session_key(self, session_id: str) -> bytes:
        """Derive a per-session key from master key using HKDF-SHA256.

        Args:
            session_id: Unique session identifier used as HKDF salt.

        Returns:
            32-byte derived key.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_SIZE,
            salt=session_id.encode("utf-8"),
            info=_HKDF_INFO,
        )
        return hkdf.derive(self._master_key)

    def encrypt_mapping(self, data: dict, session_id: str) -> bytes:
        """Encrypt a mapping dict with AES-256-GCM.

        Returns:
            nonce (12 bytes) + ciphertext (variable length).
        """
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce = secrets.token_bytes(_NONCE_SIZE)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ciphertext

    def decrypt_mapping(self, blob: bytes, session_id: str) -> dict:
        """Decrypt a mapping blob (nonce + ciphertext).

        Raises:
            ValueError: If blob is too short.
            cryptography.exceptions.InvalidTag: If key/data is wrong.
        """
        if len(blob) < _NONCE_SIZE + 1:
            raise ValueError("Encrypted blob too short")
        session_key = self.derive_session_key(session_id)
        aesgcm = AESGCM(session_key)
        nonce = blob[:_NONCE_SIZE]
        ciphertext = blob[_NONCE_SIZE:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))
