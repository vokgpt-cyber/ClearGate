"""Claude LLM adapter using the native Anthropic SDK.

Supports Claude Opus 4.6, Sonnet 4.6, and Haiku 4.5 with
extended thinking (adaptive effort levels) and streaming.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic
import structlog

from app.services.llm_adapters.base import (
    CostEstimate,
    LLMAdapter,
    ModelInfo,
    StreamChunk,
    ThinkingLevel,
)

logger = structlog.get_logger(__name__)

CLAUDE_MODELS = [
    ModelInfo(
        id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider="claude",
        context_window=1_000_000,
        supports_thinking=True,
        input_cost_per_1m=5.00,
        output_cost_per_1m=25.00,
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider="claude",
        context_window=1_000_000,
        supports_thinking=True,
        input_cost_per_1m=3.00,
        output_cost_per_1m=15.00,
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider="claude",
        context_window=200_000,
        supports_thinking=True,
        input_cost_per_1m=1.00,
        output_cost_per_1m=5.00,
    ),
]

_THINKING_MULTIPLIERS: dict[ThinkingLevel, float] = {
    "off": 0.0,
    "low": 0.1,
    "medium": 0.25,
    "high": 0.5,
    "max": 1.0,
}


class ClaudeAdapter(LLMAdapter):
    """Native adapter for the Anthropic Claude API.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Examples:
        >>> adapter = ClaudeAdapter()
        >>> async for chunk in adapter.generate("anonymized text", "Analyze this"):
        ...     print(chunk.type, chunk.content[:50])
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        anonymized_text: str,
        prompt: str,
        model: str = "claude-sonnet-4-6",
        thinking_level: ThinkingLevel = "high",
        max_tokens: int = 8192,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response from Claude with optional extended thinking."""
        logger.info(
            "claude.generate.start",
            model=model,
            thinking_level=thinking_level,
            text_length=len(anonymized_text),
            prompt_length=len(prompt),
        )

        thinking_config = self._build_thinking_config(thinking_level)
        full_message = f"{prompt}\n\nДокумент:\n{anonymized_text}"

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": full_message}],
        }
        if thinking_config:
            kwargs["thinking"] = thinking_config

        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "thinking"):
                            yield StreamChunk(type="thinking", content=delta.thinking)
                        elif hasattr(delta, "text"):
                            yield StreamChunk(type="text", content=delta.text)

                final = await stream.get_final_message()
                yield StreamChunk(
                    type="done",
                    metadata={
                        "input_tokens": final.usage.input_tokens,
                        "output_tokens": final.usage.output_tokens,
                        "model": final.model,
                        "stop_reason": final.stop_reason,
                    },
                )

            logger.info("claude.generate.done", model=model)

        except anthropic.APIError as e:
            logger.error("claude.generate.error", model=model, error=str(e))
            yield StreamChunk(type="error", content=str(e))

    def _build_thinking_config(self, level: ThinkingLevel) -> dict | None:
        """Build thinking configuration for Claude API."""
        if level == "off":
            return None
        return {"type": "adaptive", "effort": level}

    def estimate_cost(
        self,
        text: str,
        prompt: str,
        model: str = "claude-sonnet-4-6",
        thinking_level: ThinkingLevel = "high",
    ) -> CostEstimate:
        """Estimate cost based on text length and model pricing."""
        full_message = f"{prompt}\n\n{text}"
        # Rough estimate: 1 token ≈ 3 chars for Russian text
        input_tokens = max(len(full_message) // 3, 1)
        estimated_output = int(input_tokens * 0.3)
        estimated_thinking = int(
            input_tokens * _THINKING_MULTIPLIERS.get(thinking_level, 0.5)
        )

        model_info = next((m for m in CLAUDE_MODELS if m.id == model), CLAUDE_MODELS[1])

        input_cost = (input_tokens / 1_000_000) * model_info.input_cost_per_1m
        output_cost = (estimated_output / 1_000_000) * model_info.output_cost_per_1m
        thinking_cost = (estimated_thinking / 1_000_000) * model_info.output_cost_per_1m

        return CostEstimate(
            input_tokens=input_tokens,
            estimated_output_tokens=estimated_output,
            estimated_thinking_tokens=estimated_thinking,
            input_cost_usd=round(input_cost, 6),
            output_cost_usd=round(output_cost, 6),
            thinking_cost_usd=round(thinking_cost, 6),
            total_cost_usd=round(input_cost + output_cost + thinking_cost, 6),
        )

    def list_models(self) -> list[ModelInfo]:
        """Return all supported Claude models."""
        return list(CLAUDE_MODELS)

    async def health_check(self) -> bool:
        """Verify API key and connectivity with a minimal request."""
        try:
            await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            logger.warning("claude.health_check.failed", exc_info=True)
            return False
