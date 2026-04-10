"""Tests for the Claude LLM adapter (mocked — no real API calls)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm_adapters.base import CostEstimate, StreamChunk
from app.services.llm_adapters.claude import ClaudeAdapter, CLAUDE_MODELS


@pytest.fixture()
def adapter():
    return ClaudeAdapter(api_key="test-key-not-real")


class TestListModels:
    def test_returns_three_models(self, adapter):
        models = adapter.list_models()
        assert len(models) == 3

    def test_all_claude_provider(self, adapter):
        for m in adapter.list_models():
            assert m.provider == "claude"

    def test_all_support_thinking(self, adapter):
        for m in adapter.list_models():
            assert m.supports_thinking is True

    def test_model_ids(self, adapter):
        ids = {m.id for m in adapter.list_models()}
        assert "claude-opus-4-6" in ids
        assert "claude-sonnet-4-6" in ids
        assert "claude-haiku-4-5-20251001" in ids


class TestCostEstimation:
    def test_returns_cost_estimate(self, adapter):
        result = adapter.estimate_cost("test text", "prompt", "claude-sonnet-4-6")
        assert isinstance(result, CostEstimate)
        assert result.input_tokens > 0
        assert result.total_cost_usd >= 0

    def test_thinking_off_no_thinking_tokens(self, adapter):
        result = adapter.estimate_cost("text", "prompt", thinking_level="off")
        assert result.estimated_thinking_tokens == 0
        assert result.thinking_cost_usd == 0.0

    def test_thinking_max_more_tokens(self, adapter):
        low = adapter.estimate_cost("text", "prompt", thinking_level="low")
        high = adapter.estimate_cost("text", "prompt", thinking_level="max")
        assert high.estimated_thinking_tokens > low.estimated_thinking_tokens

    def test_opus_more_expensive_than_haiku(self, adapter):
        opus = adapter.estimate_cost("text", "prompt", model="claude-opus-4-6")
        haiku = adapter.estimate_cost("text", "prompt", model="claude-haiku-4-5-20251001")
        assert opus.total_cost_usd > haiku.total_cost_usd


class TestThinkingConfig:
    def test_off_returns_none(self, adapter):
        assert adapter._build_thinking_config("off") is None

    def test_high_returns_adaptive(self, adapter):
        config = adapter._build_thinking_config("high")
        assert config == {"type": "adaptive", "effort": "high"}

    def test_max_returns_adaptive(self, adapter):
        config = adapter._build_thinking_config("max")
        assert config == {"type": "adaptive", "effort": "max"}


class TestGenerate:
    @pytest.mark.asyncio
    async def test_streams_text_chunks(self, adapter):
        # Mock the streaming context manager
        mock_delta = MagicMock()
        mock_delta.text = "Hello world"
        del mock_delta.thinking  # no thinking attribute

        mock_event = MagicMock()
        mock_event.type = "content_block_delta"
        mock_event.delta = mock_delta

        mock_final = MagicMock()
        mock_final.usage.input_tokens = 100
        mock_final.usage.output_tokens = 50
        mock_final.model = "claude-sonnet-4-6"
        mock_final.stop_reason = "end_turn"

        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = mock_stream
        mock_stream.__aexit__.return_value = False
        mock_stream.__aiter__.return_value = iter([mock_event])
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        adapter.client.messages.stream = MagicMock(return_value=mock_stream)

        chunks = []
        async for chunk in adapter.generate("anonymized text", "analyze"):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.type == "text"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "Hello world"

        done_chunks = [c for c in chunks if c.type == "done"]
        assert len(done_chunks) == 1
        assert done_chunks[0].metadata["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_handles_api_error(self, adapter):
        import anthropic

        adapter.client.messages.stream = MagicMock(
            side_effect=anthropic.APIError(
                message="rate limit",
                request=MagicMock(),
                body=None,
            )
        )

        chunks = []
        async for chunk in adapter.generate("text", "prompt"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].type == "error"


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self, adapter):
        adapter.client.messages.create = AsyncMock(return_value=MagicMock())
        result = await adapter.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_unhealthy(self, adapter):
        adapter.client.messages.create = AsyncMock(side_effect=Exception("connection error"))
        result = await adapter.health_check()
        assert result is False
