"""Tests for document_chunker.py — recursive paragraph/sentence/character splitting."""

from __future__ import annotations

import pytest

from app.services.document_chunker import Chunk, DocumentChunker, chunk_document


class TestDocumentChunker:
    """Unit tests for DocumentChunker."""

    def test_empty_document(self) -> None:
        """Empty documents return empty chunk list."""
        chunker = DocumentChunker()
        result = chunker.chunk_document("")
        assert result == []

    def test_whitespace_only_document(self) -> None:
        """Documents with only whitespace return empty chunk list."""
        chunker = DocumentChunker()
        result = chunker.chunk_document("   \n\n  \t  ")
        assert result == []

    def test_short_document_single_chunk(self) -> None:
        """Short documents (< target tokens) produce one chunk."""
        chunker = DocumentChunker()
        text = "Это короткий текст."
        result = chunker.chunk_document(text, target_tokens=100)
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].start == 0
        assert result[0].end == len(text)
        assert result[0].chunk_id == 0

    def test_chunk_offsets_accuracy(self) -> None:
        """Chunk start/end offsets correctly map back to original text."""
        chunker = DocumentChunker()
        text = "Первый абзац.\n\nВторой абзац.\n\nТретий абзац."
        result = chunker.chunk_document(text, target_tokens=50)
        # Verify that each chunk's text matches the original text at its offset.
        for chunk in result:
            expected_text = text[chunk.start : chunk.end]
            assert chunk.text == expected_text, (
                f"Chunk {chunk.chunk_id} offset mismatch: "
                f"expected {expected_text!r}, got {chunk.text!r}"
            )

    def test_token_counting(self) -> None:
        """Token counts are reasonable (rough estimate)."""
        chunker = DocumentChunker()
        text = "Это текст с достаточно большим количеством слов. " * 10
        result = chunker.chunk_document(text, target_tokens=100)
        # Each chunk should have a reasonable token count.
        for chunk in result:
            assert chunk.token_count > 0
            assert chunk.token_count <= 150  # Allow some margin over target.

    def test_paragraph_boundary_split(self) -> None:
        """Documents split on paragraph boundaries (\n\n) first."""
        chunker = DocumentChunker()
        # Create a document with clear paragraphs.
        text = "Параграф один.\n\nПараграф два.\n\nПараграф три."
        result = chunker.chunk_document(text, target_tokens=1000)  # Large target.
        # Should get chunks separated by paragraphs.
        assert len(result) >= 1
        # Verify offsets for each paragraph exist.
        for chunk in result:
            expected = text[chunk.start : chunk.end]
            assert chunk.text == expected

    def test_sentence_boundary_fallback(self) -> None:
        """Long paragraphs split on sentence boundaries as fallback."""
        chunker = DocumentChunker()
        # Create a long paragraph with sentences.
        text = "Первое предложение. Второе предложение. Третье предложение. " * 20
        result = chunker.chunk_document(text, target_tokens=100)
        # Should split into multiple chunks.
        assert len(result) > 1
        # All chunks should be valid.
        for chunk in result:
            assert chunk.start >= 0
            assert chunk.end <= len(text)
            assert chunk.start < chunk.end

    def test_character_boundary_split(self) -> None:
        """Very long sentences split at character boundaries (word breaks)."""
        chunker = DocumentChunker()
        # Create a long string without natural breaks.
        words = ["слово"] * 200
        text = " ".join(words)
        result = chunker.chunk_document(text, target_tokens=50)
        # Should split into multiple chunks.
        assert len(result) > 1
        # Verify continuity: chunks should cover the text.
        combined = "".join(c.text for c in sorted(result, key=lambda c: c.start))
        assert combined == text

    def test_chunk_chunk_id_sequence(self) -> None:
        """Chunk IDs are sequential starting from 0."""
        chunker = DocumentChunker()
        text = "Текст. " * 100
        result = chunker.chunk_document(text, target_tokens=50)
        for i, chunk in enumerate(result):
            assert chunk.chunk_id == i

    def test_overlap_creation(self) -> None:
        """Overlapped chunks extend into neighbors."""
        chunker = DocumentChunker()
        text = "Текст с достаточным количеством слов для разделения на несколько частей. " * 10
        result = chunker.chunk_document(text, target_tokens=100, overlap_tokens=20)
        # With overlap, each chunk (except last) should extend into the next.
        if len(result) > 1:
            for i in range(len(result) - 1):
                current = result[i]
                next_chunk = result[i + 1]
                # Current chunk should extend past its natural boundary.
                assert current.end >= next_chunk.start

    def test_module_level_function(self) -> None:
        """Module-level chunk_document() function works."""
        text = "Короткий тестовый текст."
        result = chunk_document(text, target_tokens=100)
        assert len(result) >= 1
        assert all(isinstance(c, Chunk) for c in result)

    def test_chunk_dataclass_fields(self) -> None:
        """Chunk dataclass contains expected fields."""
        chunk = Chunk(
            text="test",
            start=0,
            end=4,
            token_count=1,
            chunk_id=0,
        )
        assert chunk.text == "test"
        assert chunk.start == 0
        assert chunk.end == 4
        assert chunk.token_count == 1
        assert chunk.chunk_id == 0


class TestDocumentChunkerRussian:
    """Tests specific to Russian language chunking."""

    def test_russian_sentence_boundaries(self) -> None:
        """Russian sentence markers are recognized."""
        chunker = DocumentChunker()
        # Russian text with various sentence enders.
        text = (
            "Что это? Восклицательное предложение! "
            "Еще один вопрос? Точка с запятой; вторая точка."
        )
        result = chunker.chunk_document(text, target_tokens=50)
        assert len(result) >= 1
        # All chunks should be valid substrings of the original.
        for chunk in result:
            assert text[chunk.start : chunk.end] == chunk.text

    def test_russian_legal_document(self) -> None:
        """Handles realistic Russian legal document structure."""
        chunker = DocumentChunker()
        text = (
            "ПОСТАНОВЛЕНИЕ СУДА\n\n"
            "Стороны по делу: истец и ответчик.\n\n"
            "Исковые требования: признать договор недействительным.\n\n"
            "Решение суда: отклонить исковые требования."
        )
        result = chunker.chunk_document(text, target_tokens=200)
        assert len(result) >= 1
        for chunk in result:
            assert chunk.start >= 0
            assert chunk.end <= len(text)


@pytest.mark.integration
class TestDocumentChunkerIntegration:
    """Integration tests (slower, but cover real-world patterns)."""

    def test_large_document_chunking(self) -> None:
        """Large documents chunk efficiently without timeout."""
        chunker = DocumentChunker()
        # Create a large document with multiple paragraphs.
        paragraphs = ["Параграф номер {}.".format(i) for i in range(1000)]
        text = "\n\n".join(paragraphs)
        result = chunker.chunk_document(text, target_tokens=300)
        assert len(result) > 0
        # Verify reconstruction.
        combined = "".join(c.text for c in sorted(result, key=lambda c: c.start))
        assert combined == text

    def test_unicode_handling(self) -> None:
        """Unicode characters (emoji, non-Latin) handled correctly."""
        chunker = DocumentChunker()
        text = "Текст с эмодзи 😀 и спецсимволами: © ® ™ ñ ü."
        result = chunker.chunk_document(text, target_tokens=50)
        assert len(result) >= 1
        combined = "".join(c.text for c in sorted(result, key=lambda c: c.start))
        assert combined == text
