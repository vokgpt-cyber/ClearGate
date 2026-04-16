"""Three-layer NER pipeline for CLEARGATE.

Orchestrates regex recognizers (Layer 1), spaCy + GLiNER NER (Layer 2),
and local LLM verification (Layer 3) to detect PII in Russian legal text.

Post-processing includes:
- Stopword filtering (legal terms, position titles)
- Adjacent PER entity merging (Фамилия + Имя Отчество → one entity)
- Overlap resolution (higher score wins, longer span breaks ties)
"""

from __future__ import annotations

import asyncio
from typing import Literal

import structlog
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult

from app.models.entities import DetectedEntity
from app.services.gliner_recognizer import GLiNERRecognizer
from app.services.local_llm_verifier import LocalLLMVerifier
from app.services.regex_recognizers import build_all_recognizers
from app.services.stopwords import is_stopword

logger = structlog.get_logger(__name__)

# Presidio entity types → CLEARGATE entity types
_PRESIDIO_TYPE_MAP: dict[str, str] = {
    "PERSON": "PER",
    "LOCATION": "LOC",
    "NLS_ENTITY": "PER",
    "ORGANIZATION": "ORG",
    "PHONE_NUMBER": "RU_PHONE",
    "EMAIL_ADDRESS": "EMAIL_ADDRESS",
    "RU_INN": "RU_INN",
    "RU_OGRN": "RU_OGRN",
    "RU_SNILS": "RU_SNILS",
    "RU_PASSPORT": "RU_PASSPORT",
    "RU_BANK_ACCOUNT": "RU_BANK_ACCOUNT",
    "RU_PHONE": "RU_PHONE",
    "RU_DATE": "RU_DATE",
    "RU_CASE_NUMBER": "RU_CASE_NUMBER",
    "RU_CONTRACT_NUMBER": "RU_CONTRACT_NUMBER",
}

# Max gap (in chars) between adjacent PER entities to merge them
_PER_MERGE_GAP = 3


class NERPipeline:
    """Three-layer NER pipeline for Russian legal documents.

    Layers:
        1. Regex (Presidio PatternRecognizers) — structured IDs with checksums
        2. NER (spaCy ru_core_news_lg + GLiNER) — names, orgs, addresses
        3. LLM (Ollama Qwen) — coreference, complex entities, verification

    Post-processing:
        - Legal stopword filtering
        - Adjacent PER entity merging
        - Overlapping span resolution
    """

    def __init__(
        self,
        spacy_model: str | None = "ru_core_news_lg",
        gliner_model: str | None = "urchade/gliner_medium-v2.1",
        ollama_model: str = "qwen2.5:7b-instruct-q4_K_M",
        enable_llm_layer: bool = True,
    ) -> None:
        self.analyzer = self._build_presidio_analyzer(spacy_model)
        self.gliner = GLiNERRecognizer(gliner_model) if gliner_model else None
        self.llm_verifier = LocalLLMVerifier(ollama_model) if enable_llm_layer else None

        logger.info(
            "ner_pipeline.init",
            spacy=spacy_model or "disabled",
            gliner=gliner_model or "disabled",
            llm=ollama_model if enable_llm_layer else "disabled",
        )

    def _build_presidio_analyzer(self, spacy_model: str | None) -> AnalyzerEngine:
        """Build Presidio analyzer with spaCy and custom recognizers."""
        nlp_engine = None

        if spacy_model:
            try:
                from presidio_analyzer.nlp_engine import NlpEngineProvider

                configuration = {
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "ru", "model_name": spacy_model}],
                }
                nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
                logger.info("ner_pipeline.spacy_loaded", model=spacy_model)
            except Exception:
                logger.warning("ner_pipeline.spacy_failed", model=spacy_model, exc_info=True)

        registry = RecognizerRegistry(supported_languages=["ru", "en"])
        registry.load_predefined_recognizers(languages=["en"])
        for recognizer in build_all_recognizers():
            registry.add_recognizer(recognizer)

        return AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["ru", "en"],
        )

    async def analyze(
        self,
        text: str,
        language: Literal["ru", "en"] = "ru",
        score_threshold: float = 0.3,
        custom_gliner_labels: list[str] | None = None,
    ) -> list[DetectedEntity]:
        """Run all enabled layers and return merged, filtered entities."""
        if not text or not text.strip():
            return []

        logger.info("ner_pipeline.analyze.start", text_length=len(text))

        # Layer 1+2: Presidio (regex recognizers + spaCy NER)
        presidio_results = await asyncio.to_thread(
            self.analyzer.analyze,
            text=text,
            language=language,
            score_threshold=score_threshold,
        )
        entities = self._convert_presidio_results(text, presidio_results)

        # Layer 2 extra: GLiNER for custom entities
        if self.gliner and custom_gliner_labels:
            gliner_results = await self.gliner.detect(text, labels=custom_gliner_labels)
            entities.extend(gliner_results)

        # Layer 3: Local LLM verification
        if self.llm_verifier:
            entities = await self.llm_verifier.verify_and_refine(text, entities)

        # Post-processing pipeline
        entities = self._filter_stopwords(entities)
        entities = self._merge_adjacent_per(entities, text)
        entities = self._merge_overlapping(entities)
        entities.sort(key=lambda e: (e.start, -e.score))

        logger.info("ner_pipeline.analyze.done", entity_count=len(entities))
        return entities

    def _convert_presidio_results(
        self,
        text: str,
        results: list[RecognizerResult],
    ) -> list[DetectedEntity]:
        """Convert Presidio RecognizerResult to DetectedEntity."""
        entities = []
        for r in results:
            entity_type = _PRESIDIO_TYPE_MAP.get(r.entity_type, r.entity_type)
            entities.append(
                DetectedEntity(
                    text=text[r.start : r.end],
                    entity_type=entity_type,
                    start=r.start,
                    end=r.end,
                    score=r.score,
                    source_layer="regex" if r.score >= 0.7 else "ner",
                    metadata={"presidio_type": r.entity_type},
                )
            )
        return entities

    def _filter_stopwords(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Remove entities that match legal/position stopwords."""
        filtered = []
        for e in entities:
            if is_stopword(e.text, e.entity_type):
                logger.debug("ner_pipeline.stopword_filtered", text=e.entity_type, entity_type=e.entity_type)
                continue
            filtered.append(e)
        return filtered

    def _merge_adjacent_per(
        self, entities: list[DetectedEntity], text: str
    ) -> list[DetectedEntity]:
        """Merge adjacent PER entities separated by whitespace/punctuation.

        Russian FIO often gets split into separate spans by spaCy:
        "Петрова" + "Алексея Николаевича" → "Петрова Алексея Николаевича"
        """
        if not entities:
            return entities

        sorted_entities = sorted(entities, key=lambda e: e.start)
        result: list[DetectedEntity] = []

        for current in sorted_entities:
            if (
                result
                and result[-1].entity_type == "PER"
                and current.entity_type == "PER"
            ):
                last = result[-1]
                gap = current.start - last.end
                # Check if the gap is small and contains only whitespace/punctuation
                if 0 <= gap <= _PER_MERGE_GAP:
                    between = text[last.end : current.start]
                    if all(c in " \t,.-" for c in between):
                        # Merge: extend the previous entity
                        merged_text = text[last.start : current.end]
                        result[-1] = DetectedEntity(
                            text=merged_text,
                            entity_type="PER",
                            start=last.start,
                            end=current.end,
                            score=max(last.score, current.score),
                            source_layer=last.source_layer,
                            metadata=last.metadata,
                        )
                        continue

            result.append(current)

        return result

    def _merge_overlapping(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Merge overlapping entity spans.

        Priority rules:
        1. Regex-validated entities (score >= 0.9) beat NER guesses
        2. Higher score wins
        3. Equal score → longer span wins
        """
        if not entities:
            return []

        sorted_entities = sorted(
            entities, key=lambda e: (e.start, -e.score, -(e.end - e.start))
        )

        merged: list[DetectedEntity] = [sorted_entities[0]]
        for current in sorted_entities[1:]:
            last = merged[-1]
            if current.start < last.end:
                # Overlap — decide which to keep
                if self._should_replace(last, current):
                    merged[-1] = current
            else:
                merged.append(current)

        return merged

    def _should_replace(self, existing: DetectedEntity, candidate: DetectedEntity) -> bool:
        """Decide if candidate should replace existing in overlap resolution."""
        # Regex-validated entities (high score) always win over NER guesses
        if candidate.score >= 0.9 and existing.score < 0.9:
            return True
        if existing.score >= 0.9 and candidate.score < 0.9:
            return False

        # Higher score wins
        if candidate.score > existing.score:
            return True
        if candidate.score < existing.score:
            return False

        # Equal score — longer span wins
        return (candidate.end - candidate.start) > (existing.end - existing.start)
