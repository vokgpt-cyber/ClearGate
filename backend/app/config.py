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

    # Kill switch for the LLM verification layer. On CPU-only pilot boxes
    # LLM verification adds 30-60 s per request; IT can disable it without
    # touching code by setting CLEARGATE_DISABLE_LLM_LAYER=true in .env.
    # Layers 1-2 (regex + spaCy NER) keep working — anonymisation quality
    # drops slightly but interactivity is restored.
    cleargate_disable_llm_layer: bool = False

    # Version (not from env -- hardcoded to match pyproject.toml)
    version: str = "0.1.0-alpha"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


settings = Settings()
