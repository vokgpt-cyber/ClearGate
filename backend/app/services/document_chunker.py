"""Document chunking for CLEARGATE with recursive paragraph/sentence/character splitting.

v0.4.0 Phase 2: BGE-M3 retrieval layer requires efficient chunking. This module
provides Russian-aware splitting with token counting via tiktoken.

Chunking hierarchy:
  1. Paragraph boundaries (\\n\\n+)
  2. Sentence boundaries (Russian: ". " "? " "! " "; ")
  3. Character boundaries at word breaks

All chunks track their char offsets in the original document for offset-based
entity mapping in Layer 3 and 4 of the NER pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import structlog
import tiktoken

logger = structlog.get_logger(__name__)

# Russian-aware sentence boundary markers.
# Include both space-after and non-space variants to handle edge cases.
_SENTENCE_BOUNDARIES_RU = r"(?<=[.!?;])\s+"
_PARAGRAPH_BOUNDARIES = r"\n\n+"
_WORD_BOUNDARY = r"\s+"


@dataclass
class Chunk:
    """A single chunk of text with metadata for offset mapping and token tracking.

    Attributes:
        text: The chunk content.
        start: Character offset in the original document.
        end: Character offset in the original document (exclusive).
        token_count: Approximate token count (via cl100k_base tokenizer).
        chunk_id: Sequential 0-indexed chunk number.
    """

    text: str
    start: int
    end: int
    token_count: int
    chunk_id: int


class DocumentChunker:
    """Splits documents into overlapping chunks with token-aware sizing.

    The recursive strategy prefers paragraph boundaries, then sentence boundaries,
    then character boundaries at word breaks. This preserves semantic units while
    keeping chunks below target token count.
    """

    def __init__(self) -> None:
        """Initialize the chunker with cl100k_base tokenizer."""
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        logger.info("document_chunker.init", encoding="cl100k_base")

    def _count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        try:
            return len(self.tokenizer.encode(text, disallowed_special=()))
        except Exception:
            # Fallback: estimate ~4 chars per token (conservative).
            return max(1, len(text) // 4)

    def chunk_document(
        self,
        text: str,
        target_tokens: int = 450,
        overlap_tokens: int = 50,
    ) -> list[Chunk]:
        """Split document into overlapping chunks.

        Args:
            text: The document to chunk.
            target_tokens: Target tokens per chunk (before overlap).
            overlap_tokens: Overlap size in tokens between adjacent chunks.

        Returns:
            List of Chunk objects with consistent char offsets.
        """
        if not text or not text.strip():
            logger.info("document_chunker.empty_text")
            return []

        logger.info(
            "document_chunker.chunk_document.start",
            text_length=len(text),
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
        )

        # Split recursively, trying paragraph → sentence → character hierarchy.
        chunks_text: list[str] = self._split_recursive(
            text,
            target_tokens=target_tokens,
        )

        # Convert text chunks to Chunk objects with offset metadata.
        offset_chunks: list[Chunk] = []
        for i, chunk_text in enumerate(chunks_text):
            # Find the offset of this chunk in the original text.
            # Use a simple linear search since chunks are produced in order.
            start = text.find(chunk_text)
            if start == -1:
                # Shouldn't happen, but handle gracefully.
                logger.warning(
                    "document_chunker.chunk_offset_not_found",
                    chunk_id=i,
                    chunk_preview=chunk_text[:50],
                )
                continue

            end = start + len(chunk_text)
            token_count = self._count_tokens(chunk_text)
            offset_chunks.append(
                Chunk(
                    text=chunk_text,
                    start=start,
                    end=end,
                    token_count=token_count,
                    chunk_id=i,
                )
            )

        # Apply overlap between chunks.
        overlapped = self._apply_overlap(
            offset_chunks,
            text,
            overlap_tokens=overlap_tokens,
        )

        logger.info(
            "document_chunker.chunk_document.done",
            chunk_count=len(overlapped),
            total_tokens=sum(c.token_count for c in overlapped),
        )
        return overlapped

    def _split_recursive(
        self,
        text: str,
        target_tokens: int,
        depth: int = 0,
    ) -> list[str]:
        """Recursively split text: paragraphs → sentences → characters.

        Args:
            text: Text to split.
            target_tokens: Target token count per chunk.
            depth: Current recursion depth (for logging).

        Returns:
            List of chunk strings.
        """
        token_count = self._count_tokens(text)

        # Base case: text fits within target.
        if token_count <= target_tokens:
            return [text]

        # Try paragraph split (depth=0).
        if depth == 0:
            paragraphs = re.split(_PARAGRAPH_BOUNDARIES, text)
            paragraphs = [p for p in paragraphs if p.strip()]
            if len(paragraphs) > 1:
                logger.debug(
                    "document_chunker.split_at_depth",
                    depth=depth,
                    split_type="paragraph",
                    parts=len(paragraphs),
                )
                result = []
                for para in paragraphs:
                    result.extend(
                        self._split_recursive(
                            para,
                            target_tokens=target_tokens,
                            depth=depth + 1,
                        )
                    )
                return result

        # Try sentence split (depth=1).
        if depth == 1:
            sentences = re.split(_SENTENCE_BOUNDARIES_RU, text)
            sentences = [s for s in sentences if s.strip()]
            if len(sentences) > 1:
                logger.debug(
                    "document_chunker.split_at_depth",
                    depth=depth,
                    split_type="sentence",
                    parts=len(sentences),
                )
                result = []
                for sentence in sentences:
                    result.extend(
                        self._split_recursive(
                            sentence,
                            target_tokens=target_tokens,
                            depth=depth + 1,
                        )
                    )
                return result

        # Character split at word boundaries (depth>=2).
        logger.debug(
            "document_chunker.split_at_depth",
            depth=depth,
            split_type="character",
        )
        words = re.split(_WORD_BOUNDARY, text)
        words = [w for w in words if w.strip()]

        if not words:
            # Last resort: return the text as-is even if it exceeds target.
            return [text]

        # Greedy packing of words into chunks.
        chunks = []
        current_chunk = ""
        for word in words:
            test_chunk = current_chunk + word
            if self._count_tokens(test_chunk) <= target_tokens:
                current_chunk = test_chunk
            else:
                # Word would exceed target; start a new chunk.
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = word

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _apply_overlap(
        self,
        chunks: list[Chunk],
        original_text: str,
        overlap_tokens: int,
    ) -> list[Chunk]:
        """Apply token-based overlap between chunks.

        Creates a sliding window overlap by extending the end of each chunk
        (except the last) into the beginning of the next chunk.

        Args:
            chunks: Chunks with original offsets.
            original_text: The original document text.
            overlap_tokens: Number of tokens to overlap.

        Returns:
            New chunks with overlapped regions.
        """
        if len(chunks) <= 1:
            return chunks

        # Calculate token budget per overlap: how many chars for overlap_tokens.
        # Use a simple heuristic: ~4 chars per token.
        overlap_chars_budget = overlap_tokens * 4

        result = []
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                # Last chunk: no overlap after.
                result.append(chunk)
            else:
                # Find overlap with the next chunk.
                next_chunk = chunks[i + 1]
                overlap_start = max(chunk.start + chunk.token_count * 4 - overlap_chars_budget, chunk.start)
                overlap_end = min(chunk.end + overlap_chars_budget, next_chunk.end)

                # Create overlapped chunk.
                new_text = original_text[chunk.start : overlap_end]
                new_token_count = self._count_tokens(new_text)
                result.append(
                    Chunk(
                        text=new_text,
                        start=chunk.start,
                        end=overlap_end,
                        token_count=new_token_count,
                        chunk_id=chunk.chunk_id,
                    )
                )

        return result


# Module-level instance for convenience.
_default_chunker: DocumentChunker | None = None


def get_chunker() -> DocumentChunker:
    """Get or create the default chunker instance."""
    global _default_chunker
    if _default_chunker is None:
        _default_chunker = DocumentChunker()
    return _default_chunker


def chunk_document(
    text: str,
    target_tokens: int = 450,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Convenience function: split a document using the default chunker."""
    return get_chunker().chunk_document(text, target_tokens, overlap_tokens)
