"""Base interface for LLM adapters.

All cloud LLM providers (Claude, OpenAI, Gemini) implement this interface.
Each adapter uses the provider's native SDK — no unified shims (see ADR-0006).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

ThinkingLevel = Literal["off", "low", "medium", "high", "max"]
Provider = Literal["claude", "openai", "gemini"]


class StreamChunk(BaseModel):
    """A single chunk from an LLM streaming response."""

    type: Literal["thinking", "text", "done", "error"]
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostEstimate(BaseModel):
    """Estimated cost breakdown for an LLM request."""

    input_tokens: int
    estimated_output_tokens: int
    estimated_thinking_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    thinking_cost_usd: float
    total_cost_usd: float


class ModelInfo(BaseModel):
    """Information about a supported LLM model."""

    id: str
    name: str
    provider: Provider
    context_window: int
    supports_thinking: bool
    input_cost_per_1m: float
    output_cost_per_1m: float


class LLMAdapter(ABC):
    """Abstract interface for cloud LLM adapters.

    Each implementation wraps a provider's native SDK and exposes
    a uniform streaming interface for the CLEARGATE application.
    """

    @abstractmethod
    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel = "high",
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response from the LLM.

        Args:
            anonymized_text: Pre-anonymized document text (NEVER raw PII).
            prompt: User's prompt/instruction.
            model: Model identifier.
            thinking_level: Extended thinking effort level.
            max_tokens: Maximum output tokens.

        Yields:
            StreamChunk objects (thinking, text, done, or error).
        """

    @abstractmethod
    def estimate_cost(
        self,
        text: str,
        prompt: str,
        model: str,
        thinking_level: ThinkingLevel = "high",
    ) -> CostEstimate:
        """Estimate the cost of a request before sending it."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """Return list of supported models for this provider."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the API is reachable and the key is valid."""
