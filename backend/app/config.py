"""Application configuration via environment variables and .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root .env is one level above backend/
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

_DEFAULT_CORS = "http://localhost:3000,http://localhost:1420,tauri://localhost"


class Settings(BaseSettings):
    """CLEARGATE backend settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Deployment profile
    cleargate_profile: str = "alpha"

    # Server
    backend_host: str = "0.0.0.0"  # noqa: S104
    backend_port: int = 8000

    # CORS
    backend_cors_origins: str = _DEFAULT_CORS

    # Logging
    log_level: str = "INFO"

    # Session persistence
    session_store_dir: str = "data"  # relative to backend/, or absolute path
    session_ttl_minutes: int = 1440  # 24 hours

    # Local LLM (Ollama) — surfaced in settings so startup logging can
    # show the resolved value without re-reading the env var by hand.
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M"

    # Layer-2 NER models. Resolved from env vars SPACY_MODEL and GLINER_MODEL
    # (pydantic-settings auto-uppercases the field name). Defaults are the
    # large/medium-quality choices baked into the backend image.
    spacy_model: str = "ru_core_news_lg"
    gliner_model: str = "urchade/gliner_medium-v2.1"

    # Default zero-shot labels GLiNER searches for when a session does not
    # supply its own custom_entities list. Mix of English and Russian-
    # specific legal terms. CSV-encoded so a single env var can override.
    cleargate_default_gliner_labels: str = (
        "person,organization,location,address,"
        "должность,сумма контракта,наименование суда,кодовое название проекта"
    )

    # BGE-M3 embedder URL (Phase 2 retrieval).
    embedder_url: str = "http://bge-embedder:80"

    # Kill switch for the LLM verification layer. On CPU-only pilot boxes
    # LLM verification adds 30-60 s per request; IT can disable it without
    # touching code by setting CLEARGATE_DISABLE_LLM_LAYER=true in .env.
    # Layers 1-2 (regex + spaCy NER) keep working — anonymisation quality
    # drops slightly but interactivity is restored.
    cleargate_disable_llm_layer: bool = False

    # Auth (Sprint B.2) — HMAC secret for signing HttpOnly session cookies.
    # Must be stable across restarts (otherwise all users are logged out on
    # every redeploy). Empty string triggers a one-time auto-generation into
    # data/session_cookie.key at startup; IT can also set it explicitly via
    # CLEARGATE_SESSION_COOKIE_SECRET in .env for reproducible deployments.
    cleargate_session_cookie_secret: str = ""

    # Auth session cookie lifetime. Independent of anonymization session TTL
    # so lawyers stay logged in across multiple document sessions.
    cleargate_auth_session_ttl_minutes: int = 720  # 12 hours

    # Cookie name — kept short and opaque so nothing leaks about the stack
    # to anyone inspecting browser devtools.
    cleargate_auth_cookie_name: str = "cg_session"

    # LDAP/AD authentication (v0.4.0 Phase 3). If LDAP_URL is empty, auth
    # falls back to local password-only mode. Production GPU deployment fills
    # these via .env; pilot leaves them blank.
    ldap_url: str = ""                # e.g. "ldaps://ad.epam.ru:636"
    ldap_bind_dn: str = ""            # service account DN for directory queries
    ldap_bind_password: str = ""      # service account password
    ldap_base_dn: str = ""            # base DN for user searches
    ldap_admin_group_dn: str = ""     # group DN that maps to admin role
    ldap_user_group_dn: str = ""      # group DN that maps to lawyer role
    ldap_timeout_seconds: int = 5     # connect timeout, prevents hangs

    # Version (not from env -- hardcoded to match pyproject.toml)
    version: str = "1.0.1"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def default_gliner_labels_list(self) -> list[str]:
        """Parse default GLiNER labels from CSV string."""
        return [
            label.strip()
            for label in self.cleargate_default_gliner_labels.split(",")
            if label.strip()
        ]


settings = Settings()
