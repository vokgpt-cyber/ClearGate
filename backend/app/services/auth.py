"""Authentication primitives: password hashing + signed session tokens.

All user-facing auth boils down to two operations:
  1. hash_password / verify_password -- Argon2id, via argon2-cffi
  2. issue_session_token / verify_session_token -- HMAC-signed opaque token
     stored in an HttpOnly cookie, carrying only a user_id + issue time.

We deliberately keep the token payload minimal.  Anything else (username,
last login, permissions) must be re-resolved from UserStore on every
request so that disabling a user takes effect immediately, without
waiting for the cookie to expire.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = structlog.get_logger(__name__)

# Argon2id parameters — tuned for pilot CPU-only deployment.  These are
# OWASP's 2023 "second recommended" profile: still strong, cheap enough
# that a cold login doesn't feel laggy on the 32 GB Windows Server VM.
_ARGON2_TIME_COST = 2
_ARGON2_MEMORY_COST = 65536  # 64 MiB
_ARGON2_PARALLELISM = 1
_ARGON2_HASH_LEN = 32
_ARGON2_SALT_LEN = 16

# Token versioning lets us rotate the signing scheme later without
# invalidating older cookies on the spot.  Bump when changing the
# signer salt or serializer settings.
_TOKEN_SALT = "cleargate.auth.session.v1"


@dataclass(frozen=True)
class SessionToken:
    """Result of decoding a cookie — only user_id is trusted."""

    user_id: str


class AuthService:
    """Argon2 password hashing + HMAC-signed session cookies.

    Thread-safe: argon2-cffi's PasswordHasher is thread-safe, and
    itsdangerous's serializer is stateless.
    """

    def __init__(self, signing_secret: str, max_age_seconds: int) -> None:
        if not signing_secret:
            raise ValueError("AuthService requires a non-empty signing_secret")
        self._hasher = PasswordHasher(
            time_cost=_ARGON2_TIME_COST,
            memory_cost=_ARGON2_MEMORY_COST,
            parallelism=_ARGON2_PARALLELISM,
            hash_len=_ARGON2_HASH_LEN,
            salt_len=_ARGON2_SALT_LEN,
        )
        self._serializer = URLSafeTimedSerializer(
            secret_key=signing_secret, salt=_TOKEN_SALT
        )
        self._max_age_seconds = max_age_seconds

    # ------------------------------------------------------------------
    # Passwords
    # ------------------------------------------------------------------

    def hash_password(self, plaintext: str) -> str:
        """Return an Argon2id hash for storage.  Plaintext is never logged."""
        if not plaintext:
            raise ValueError("password cannot be empty")
        return self._hasher.hash(plaintext)

    def verify_password(self, plaintext: str, stored_hash: str) -> bool:
        """Constant-time password verification.  Returns False on any failure."""
        if not plaintext or not stored_hash:
            return False
        try:
            self._hasher.verify(stored_hash, plaintext)
        except (VerifyMismatchError, InvalidHashError):
            return False
        except Exception:
            # Argon2 can raise unexpected errors on corrupt hashes --
            # treat any surprise as a failed login rather than 500ing.
            logger.warning("auth.verify_password.unexpected_error", exc_info=True)
            return False
        return True

    def needs_rehash(self, stored_hash: str) -> bool:
        """True when the hash was made with older Argon2 parameters."""
        try:
            return self._hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return True

    # ------------------------------------------------------------------
    # Session tokens
    # ------------------------------------------------------------------

    def issue_session_token(self, user_id: str) -> str:
        """Sign an opaque, time-stamped token carrying only the user_id."""
        if not user_id:
            raise ValueError("user_id cannot be empty")
        return self._serializer.dumps({"uid": user_id})

    def verify_session_token(self, token: str) -> SessionToken | None:
        """Decode a cookie.  Returns None on any failure (expired, tampered, malformed)."""
        if not token:
            return None
        try:
            payload = self._serializer.loads(token, max_age=self._max_age_seconds)
        except SignatureExpired:
            logger.info("auth.token.expired")
            return None
        except BadSignature:
            logger.warning("auth.token.bad_signature")
            return None
        except Exception:
            logger.warning("auth.token.decode_error", exc_info=True)
            return None
        if not isinstance(payload, dict):
            return None
        uid = payload.get("uid")
        if not isinstance(uid, str) or not uid:
            return None
        return SessionToken(user_id=uid)

    @property
    def max_age_seconds(self) -> int:
        return self._max_age_seconds


# ----------------------------------------------------------------------
# Singleton + lazy init
# ----------------------------------------------------------------------

_instance: AuthService | None = None


def init_auth_service(signing_secret: str, max_age_seconds: int) -> AuthService:
    """Install the process-wide AuthService.  Called once from lifespan startup."""
    global _instance
    _instance = AuthService(signing_secret=signing_secret, max_age_seconds=max_age_seconds)
    return _instance


def get_auth_service() -> AuthService:
    """Return the installed AuthService.  Raises if init_auth_service was never called."""
    if _instance is None:
        raise RuntimeError("AuthService not initialised -- call init_auth_service() first")
    return _instance


def reset_auth_service() -> None:
    """Test-only: drop the singleton so the next get_auth_service() re-initialises."""
    global _instance
    _instance = None


# ----------------------------------------------------------------------
# Signing-secret bootstrap
# ----------------------------------------------------------------------


def resolve_signing_secret(
    configured: str,
    secret_file_path: Path,
) -> str:
    """Resolve the HMAC secret from config or an auto-generated on-disk key.

    Precedence:
      1. If ``configured`` (from CLEARGATE_SESSION_COOKIE_SECRET) is non-empty,
         use it verbatim.  This is the deterministic path for IT-managed
         deployments that rotate secrets via config management.
      2. Otherwise, read/create ``secret_file_path``.  File permissions
         cannot be tightened portably on Windows Server, so we document
         in the deployment guide that the ``data/`` directory must inherit
         the same ACL as the rest of the backend's working data.

    Always returns a non-empty string.
    """
    if configured:
        return configured
    if secret_file_path.exists():
        raw = secret_file_path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
        logger.warning("auth.signing_secret.empty_file_regenerating", path=str(secret_file_path))
    secret_file_path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(64)
    secret_file_path.write_text(generated, encoding="utf-8")
    logger.info("auth.signing_secret.generated", path=str(secret_file_path))
    return generated
