"""BGE-M3 embedder retrieval layer for CLEARGATE v0.4.0.

BGE-M3 is served via HuggingFace TEI (Text Embedding Inference) at
http://bge-embedder:80 with an OpenAI-compatible /embed API.

This layer provides relevance-based filtering for Layer 3 of the NER pipeline:
for each ambiguous candidate entity, retrieve the top-3 most relevant chunks
to pass as focused context to Layer 4 (LLM verification).

Gracefully degrades if BGE is unreachable: falls back to using whole-document
context (slower but functional).
"""

from __future__ import annotations

import os
from typing import Sequence

import httpx
import numpy as np
import structlog

from app.services.document_chunker import Chunk

logger = structlog.get_logger(__name__)

# Default endpoint if not configured.
_DEFAULT_EMBEDDER_URL = "http://localhost:8002"


class BGERetriever:
    """Wraps HuggingFace TEI BGE-M3 embedder.

    Provides chunk embedding and similarity-based retrieval for focused
    context during Layer 3-4 entity verification.
    """

    def __init__(self, base_url: str | None = None) -> None:
        """Initialize the retriever.

        Args:
            base_url: TEI embedder HTTP endpoint.
                If not given, falls back to EMBEDDER_URL env var,
                then to http://localhost:8002.
        """
        self.base_url = (
            base_url
            or os.environ.get("EMBEDDER_URL", _DEFAULT_EMBEDDER_URL)
        ).rstrip("/")
        # Ensure the URL includes /embed path for the TEI endpoint.
        if not self.base_url.endswith("/embed"):
            self.base_url = self.base_url + "/embed"

        self._embedding_dim: int | None = None
        logger.info("bge_retriever.init", base_url=self.base_url)

    async def embed_chunks(
        self,
        chunks: Sequence[Chunk],
    ) -> np.ndarray:
        """Batch-embed all chunks.

        Args:
            chunks: List of Chunk objects.

        Returns:
            Array of shape (n_chunks, embedding_dim).
            Returns empty array if embedding fails.
        """
        if not chunks:
            return np.array([], dtype=np.float32).reshape(0, 0)

        texts = [chunk.text for chunk in chunks]
        try:
            embeddings = await self._embed_texts(texts)
            logger.info(
                "bge_retriever.embed_chunks.done",
                chunk_count=len(chunks),
                embedding_shape=embeddings.shape,
            )
            return embeddings
        except Exception:
            logger.warning(
                "bge_retriever.embed_chunks.failed",
                chunk_count=len(chunks),
                exc_info=True,
            )
            # Graceful degradation: return empty array, caller falls back to
            # whole-document context.
            return np.array([], dtype=np.float32).reshape(len(chunks), 0)

    async def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query string.

        Args:
            text: The query text.

        Returns:
            1D array of embedding values.
            Returns empty array if embedding fails.
        """
        try:
            embeddings = await self._embed_texts([text])
            if embeddings.shape[0] > 0:
                return embeddings[0, :]
            return np.array([], dtype=np.float32)
        except Exception:
            logger.warning(
                "bge_retriever.embed_query.failed",
                text_length=len(text),
                exc_info=True,
            )
            return np.array([], dtype=np.float32)

    async def find_relevant_chunks(
        self,
        query: str,
        chunk_embeddings: np.ndarray,
        chunks: Sequence[Chunk],
        top_k: int = 3,
    ) -> list[Chunk]:
        """Find the most relevant chunks for a query using cosine similarity.

        Args:
            query: Query text (e.g., entity text + context window).
            chunk_embeddings: Pre-computed chunk embeddings (n_chunks, dim).
            chunks: Corresponding chunks.
            top_k: Number of top results to return.

        Returns:
            List of top-k most relevant chunks.
        """
        if not chunks or chunk_embeddings.size == 0:
            logger.debug("bge_retriever.find_relevant_chunks.no_embeddings")
            return []

        query_embedding = await self.embed_query(query)
        if query_embedding.size == 0:
            logger.warning("bge_retriever.find_relevant_chunks.query_embedding_failed")
            return []

        # Cosine similarity: (embedding · query) / (||embedding|| * ||query||)
        norms_chunks = np.linalg.norm(chunk_embeddings, axis=1, keepdims=True)
        norms_chunks = np.where(norms_chunks > 0, norms_chunks, 1.0)  # Avoid division by zero.

        norm_query = np.linalg.norm(query_embedding)
        if norm_query == 0:
            return []

        normalized_chunks = chunk_embeddings / norms_chunks
        normalized_query = query_embedding / norm_query

        similarities = np.dot(normalized_chunks, normalized_query)

        # Get top-k indices.
        top_k = min(top_k, len(chunks))
        top_indices = np.argsort(-similarities)[:top_k]

        result = [chunks[i] for i in top_indices]
        logger.debug(
            "bge_retriever.find_relevant_chunks.done",
            query_length=len(query),
            top_k=top_k,
            top_similarities=similarities[top_indices].tolist(),
        )
        return result

    async def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """Call the TEI /embed endpoint to embed multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            Array of shape (len(texts), embedding_dim).

        Raises:
            Exception if the request fails.
        """
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, 0)

        payload = {"inputs": texts}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.base_url, json=payload)
            response.raise_for_status()

        data = response.json()

        # TEI /embed returns a list of embeddings (one per input text).
        # Convert to numpy array.
        if isinstance(data, list):
            embeddings = np.array(data, dtype=np.float32)
        elif isinstance(data, dict) and "embeddings" in data:
            embeddings = np.array(data["embeddings"], dtype=np.float32)
        else:
            raise ValueError(f"Unexpected TEI response format: {type(data)}")

        if embeddings.ndim != 2:
            raise ValueError(f"Expected 2D embeddings, got shape {embeddings.shape}")

        return embeddings
