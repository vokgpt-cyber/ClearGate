"""Tests for bge_retriever.py — BGE-M3 embedder integration."""

from __future__ import annotations

import pytest

import numpy as np

from app.services.bge_retriever import BGERetriever
from app.services.document_chunker import Chunk


class TestBGERetriever:
    """Unit tests for BGERetriever."""

    def test_initialization_default_url(self) -> None:
        """Retriever initializes with default URL."""
        retriever = BGERetriever()
        assert retriever.base_url == "http://localhost:8002/embed"

    def test_initialization_custom_url(self) -> None:
        """Retriever accepts custom base URL."""
        retriever = BGERetriever(base_url="http://bge-service:8000")
        assert retriever.base_url == "http://bge-service:8000/embed"

    def test_url_normalization_strips_trailing_slash(self) -> None:
        """URL normalization removes trailing slashes."""
        retriever = BGERetriever(base_url="http://example.com/")
        assert not retriever.base_url.endswith("//")

    def test_url_normalization_adds_embed_path(self) -> None:
        """URL normalization adds /embed if missing."""
        retriever = BGERetriever(base_url="http://example.com")
        assert retriever.base_url.endswith("/embed")

    async def test_embed_chunks_empty_list(self) -> None:
        """Embedding empty chunk list returns empty array."""
        retriever = BGERetriever()
        result = await retriever.embed_chunks([])
        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 0

    async def test_embed_query_returns_array(self) -> None:
        """embed_query returns a 1D array."""
        retriever = BGERetriever()
        # This will fail to connect, but should return empty array gracefully.
        result = await retriever.embed_query("test query")
        assert isinstance(result, np.ndarray)
        assert result.ndim == 1

    def test_chunk_fixtures(self) -> None:
        """Create test chunks for retrieval tests."""
        chunks = [
            Chunk(
                text="Текст про компанию АО Газпром.",
                start=0,
                end=30,
                token_count=5,
                chunk_id=0,
            ),
            Chunk(
                text="Текст про адрес в Москве, улица Тверская.",
                start=30,
                end=70,
                token_count=7,
                chunk_id=1,
            ),
            Chunk(
                text="Текст про судебное решение от 1 января 2024 года.",
                start=70,
                end=120,
                token_count=8,
                chunk_id=2,
            ),
        ]
        assert len(chunks) == 3
        assert all(isinstance(c, Chunk) for c in chunks)

    async def test_find_relevant_chunks_empty_embeddings(self) -> None:
        """find_relevant_chunks handles empty embeddings gracefully."""
        retriever = BGERetriever()
        chunks = [
            Chunk(
                text="test", start=0, end=4, token_count=1, chunk_id=0
            )
        ]
        embeddings = np.array([], dtype=np.float32).reshape(len(chunks), 0)
        result = await retriever.find_relevant_chunks("query", embeddings, chunks)
        assert result == []

    async def test_find_relevant_chunks_zero_norm(self) -> None:
        """find_relevant_chunks handles zero-norm embeddings safely."""
        retriever = BGERetriever()
        chunks = [
            Chunk(
                text="test", start=0, end=4, token_count=1, chunk_id=0
            )
        ]
        # Create zero-valued embeddings.
        embeddings = np.zeros((1, 768), dtype=np.float32)
        result = await retriever.find_relevant_chunks("query", embeddings, chunks)
        # Should handle gracefully and return empty or original.
        assert isinstance(result, list)


@pytest.mark.integration
class TestBGERetrieverIntegration:
    """Integration tests (require BGE service running)."""

    @pytest.mark.skip(reason="Requires BGE service running")
    async def test_embed_chunks_real_service(self) -> None:
        """Integration: embed chunks with real BGE service."""
        retriever = BGERetriever(base_url="http://localhost:8002")
        chunks = [
            Chunk(
                text="Компания АО Газпром находится в Москве.",
                start=0,
                end=42,
                token_count=6,
                chunk_id=0,
            ),
            Chunk(
                text="Судебное решение от 1 января 2024 года.",
                start=42,
                end=82,
                token_count=7,
                chunk_id=1,
            ),
        ]
        embeddings = await retriever.embed_chunks(chunks)
        assert embeddings.shape == (2, 1024)  # BGE-M3 produces 1024-dim vectors.

    @pytest.mark.skip(reason="Requires BGE service running")
    async def test_find_relevant_chunks_real_service(self) -> None:
        """Integration: retrieve chunks with real BGE service."""
        retriever = BGERetriever(base_url="http://localhost:8002")
        chunks = [
            Chunk(
                text="Текст про компанию Газпром.",
                start=0,
                end=27,
                token_count=4,
                chunk_id=0,
            ),
            Chunk(
                text="Текст про суд в Москве.",
                start=27,
                end=50,
                token_count=4,
                chunk_id=1,
            ),
            Chunk(
                text="Текст про договор поставки газа.",
                start=50,
                end=82,
                token_count=5,
                chunk_id=2,
            ),
        ]
        embeddings = await retriever.embed_chunks(chunks)
        result = await retriever.find_relevant_chunks(
            "компания Газпром", embeddings, chunks, top_k=2
        )
        assert len(result) <= 2
        # First result should be the company-related chunk.
        assert any("Газпром" in c.text for c in result)
