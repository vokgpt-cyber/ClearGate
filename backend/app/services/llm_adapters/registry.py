"""LLM adapter registry — maps provider names to adapter instances."""

from __future__ import annotations

from app.services.llm_adapters.base import LLMAdapter, ModelInfo, Provider
from app.services.llm_adapters.claude import ClaudeAdapter


def get_adapter(provider: Provider, api_key: str | None = None) -> LLMAdapter:
    """Get an LLM adapter instance for the given provider.

    Args:
        provider: "claude", "openai", or "gemini".
        api_key: Optional API key override.

    Returns:
        An initialized LLMAdapter.

    Raises:
        ValueError: If provider is not supported.
    """
    if provider == "claude":
        return ClaudeAdapter(api_key=api_key)
    raise ValueError(f"Unsupported provider: {provider}. Available: claude")


def list_all_models() -> list[ModelInfo]:
    """Return models from all registered providers."""
    models: list[ModelInfo] = []
    models.extend(ClaudeAdapter().list_models())
    return models
