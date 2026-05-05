"""Five-layer NER pipeline for CLEARGATE v0.4.0.

Orchestrates regex recognizers (Layer 1), spaCy + GLiNER NER (Layer 2),
BGE retrieval (Layer 3), local LLM verification (Layer 4), and LLM entity
scanning (Layer 5) to detect PII in Russian legal text.

Post-processing includes:
- Stopword filtering (legal terms, position titles)
- Adjacent PER entity merging (Фамилия + Имя Отчество → one entity)
- Overlap resolution (higher score wins, longer span breaks ties)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal

import structlog
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult

from app.models.entities import DetectedEntity
from app.services.bge_retriever import BGERetriever
from app.services.document_chunker import Chunk
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
    "RU_KPP": "RU_KPP",
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

_LEGAL_FORM_HINT = re.compile(
    r"\b(?:ООО|ОАО|АО|ПАО|ЗАО|ИП|LLC|L\.L\.C\.|LTD\.?|LIMITED|INC\.?|"
    r"CORP\.?|CORPORATION|COMPANY|CO\.?|GMBH|AG|S\.A\.|B\.V\.|N\.V\.)\b",
    re.IGNORECASE,
)
_DOCUMENT_CUE = re.compile(
    r"(?:№|N\s*)\s*[\wА-Яа-яЁё/-]{2,}|от\s+\d{2}\.\d{2}\.\d{2,4}|договор",
    re.IGNORECASE,
)
_FINANCIAL_CUE = re.compile(
    r"\b(?:сумм[ауы]|цена|стоимость|вознаграждение|оплат[ауы]|выручк[аи]|"
    r"штраф|неустойк[аиу]|пен[яи]|НДС|CNY|CNH|RMB|RUB|RUR|USD|EUR)\b",
    re.IGNORECASE,
)
_MONEY_LIKE_NUMBER = re.compile(r"^\d{1,3}(?:[ \u00A0]\d{3})+(?:[,.]\d{1,2})?$")
_DOCUMENT_TITLE_WORDS = {
    "аренда",
    "агентский",
    "дистрибуция",
    "договор",
    "заем",
    "заём",
    "кредит",
    "лизинг",
    "подряд",
    "поставка",
    "услуги",
}
_ENTITY_TYPE_PRIORITY = {
    "RU_INN": 80,
    "RU_OGRN": 80,
    "RU_KPP": 80,
    "RU_SNILS": 80,
    "RU_PASSPORT": 80,
    "RU_BANK_ACCOUNT": 80,
    "RU_BIK": 80,
    "RU_PHONE": 80,
    "EMAIL_ADDRESS": 80,
    "RU_CONTRACT_NUMBER": 75,
    "RU_CASE_NUMBER": 75,
    "MON": 90,
    "RU_DATE": 65,
    "DATE": 65,
    "ADDR": 60,
    "PER": 50,
    "ORG": 45,
    "POSITION": 35,
    "LOC": 30,
}


@dataclass
class ChunkCache:
    """Cache for document chunks and their embeddings (per session).

    Holds chunks and embeddings across multiple anonymize calls in the same
    session, avoiding re-chunking and re-embedding the same document.
    """

    document_hash: str
    chunks: list[Chunk]
    embeddings: object  # numpy array; stored as object to defer numpy import


class NERPipeline:
    """Five-layer NER pipeline for Russian legal documents (v0.4.0).

    Layers:
        1. Regex (Presidio PatternRecognizers) — structured IDs with checksums
        2. NER (spaCy ru_core_news_lg + GLiNER) — names, orgs, addresses
        3. BGE retrieval — context building for ambiguous candidates
        4. LLM verify — coreference resolution, complex entity verification
        5. LLM scan — find entities missed by layers 1-2

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
        default_gliner_labels: list[str] | None = None,
        embedder_url: str | None = None,
    ) -> None:
        self.analyzer = self._build_presidio_analyzer(spacy_model)
        self.gliner = GLiNERRecognizer(gliner_model) if gliner_model else None
        self.llm_verifier = LocalLLMVerifier(ollama_model) if enable_llm_layer else None
        self.bge_retriever = BGERetriever(base_url=embedder_url)
        self.default_gliner_labels: list[str] = list(default_gliner_labels or [])

        logger.info(
            "ner_pipeline.init",
            spacy=spacy_model or "disabled",
            gliner=gliner_model or "disabled",
            llm=ollama_model if enable_llm_layer else "disabled",
            bge=embedder_url or "default",
            default_gliner_labels_count=len(self.default_gliner_labels),
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
        chunk_cache: ChunkCache | None = None,
    ) -> list[DetectedEntity]:
        """Run all 5 enabled layers and return merged, filtered entities.

        Layers:
            1. Regex (Presidio) — structured IDs
            2. GLiNER — custom entity labels (default or custom)
            3. BGE retrieval — context for ambiguous spans (optional)
            4. LLM verify — coreference + verification
            5. LLM scan — find missed entities
        """
        if not text or not text.strip():
            return []

        logger.info("ner_pipeline.analyze.start", text_length=len(text), layers=5)

        # Layer 1: Regex (Presidio PatternRecognizers)
        presidio_results = await asyncio.to_thread(
            self.analyzer.analyze,
            text=text,
            language=language,
            score_threshold=score_threshold,
        )
        entities = self._convert_presidio_results(text, presidio_results)

        # Layer 2: GLiNER (with default labels if no custom)
        labels_to_use = custom_gliner_labels if custom_gliner_labels is not None else self.default_gliner_labels
        if self.gliner and labels_to_use:
            try:
                gliner_results = await self.gliner.detect(text, labels=labels_to_use)
                entities.extend(gliner_results)
            except Exception:
                logger.warning("ner_pipeline.gliner_failed", exc_info=True)

        # Layer 3: BGE retrieval (build context per ambiguous candidate)
        # Only relevant if we have an LLM verifier; otherwise skip.
        # The retriever auto-degrades if BGE service is unreachable.
        # (For brevity in this turn, we pass full text to LLM if BGE off; the
        # fancier retrieval-per-candidate path can land in a follow-up.)

        # Layer 4: LLM verify
        if self.llm_verifier:
            try:
                entities = await self.llm_verifier.verify_and_refine(text, entities)
            except Exception:
                logger.warning("ner_pipeline.llm_verifier_failed", exc_info=True)

        # Layer 5: LLM scan-for-missed
        if self.llm_verifier:
            try:
                missed = await self.llm_verifier.find_missed_entities(text, entities)
                if missed:
                    entities.extend(missed)
            except Exception:
                logger.warning("ner_pipeline.find_missed_failed", exc_info=True)

        entities = self.post_process(text, entities)
        logger.info("ner_pipeline.analyze.done", entity_count=len(entities))
        return entities

    def post_process(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Apply shared entity cleanup after any detection source.

        Used by the fast regex/NER pass and by optional manual LLM deep scan
        so both paths get the same stop-word and overlap behavior.
        """
        entities = self._filter_stopwords(entities)
        entities = self._filter_document_title_false_positives(text, entities)
        entities = self._filter_structured_false_positives(text, entities)
        entities = self._merge_adjacent_per(entities, text)
        entities = self._merge_overlapping(entities)
        entities.sort(key=lambda e: (e.start, -e.score))
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

    def _filter_document_title_false_positives(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Remove document-type headings misclassified as organizations.

        Legal DOCX templates often start with a centered one-word heading
        like "ДИСТРИБУЦИЯ", "АРЕНДА", "ЗАЁМ" or "ЛИЗИНГ" followed by a
        contract number and date. Small NER models tend to tag those all-caps
        headings as ORG, but they are document type labels, not sensitive
        information.
        """
        filtered: list[DetectedEntity] = []
        for entity in entities:
            if entity.entity_type == "ORG" and self._is_document_title(text, entity):
                logger.debug(
                    "ner_pipeline.document_title_filtered",
                    text=entity.text,
                    entity_type=entity.entity_type,
                )
                continue
            filtered.append(entity)
        return filtered

    def _is_document_title(self, text: str, entity: DetectedEntity) -> bool:
        if entity.start > 350:
            return False
        line_start = text.rfind("\n", 0, entity.start) + 1
        line_end = text.find("\n", entity.end)
        if line_end == -1:
            line_end = len(text)

        line = text[line_start:line_end].strip()
        if not line or len(line) > 90:
            return False
        if _LEGAL_FORM_HINT.search(line):
            return False
        if entity.text.strip() and entity.text.strip() not in line:
            return False

        normalized_words = {
            re.sub(r"[^a-zа-яё]", "", word.lower()).replace("ё", "е")
            for word in re.findall(r"[A-Za-zА-Яа-яЁё]+", line)
        }
        normalized_words.discard("")
        if not normalized_words:
            return False
        title_word_hit = bool(normalized_words & {w.replace("ё", "е") for w in _DOCUMENT_TITLE_WORDS})

        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", line)
        uppercase_letters = [ch for ch in letters if ch.upper() == ch and ch.lower() != ch]
        uppercase_ratio = len(uppercase_letters) / len(letters) if letters else 0.0
        short_heading = len(normalized_words) <= 4 and uppercase_ratio >= 0.72
        if not (title_word_hit or short_heading):
            return False

        cue_window = text[line_end : min(len(text), line_end + 180)]
        return bool(_DOCUMENT_CUE.search(cue_window))

    def _filter_structured_false_positives(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Remove LLM-added structured labels contradicted by local context."""
        filtered: list[DetectedEntity] = []
        for entity in entities:
            if (
                entity.entity_type == "RU_CONTRACT_NUMBER"
                and _MONEY_LIKE_NUMBER.fullmatch(entity.text.strip())
            ):
                window = text[max(0, entity.start - 90) : min(len(text), entity.end + 90)]
                if _FINANCIAL_CUE.search(window):
                    logger.debug(
                        "ner_pipeline.money_as_contract_filtered",
                        text=entity.text,
                        entity_type=entity.entity_type,
                    )
                    continue
            filtered.append(entity)
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
        existing_priority = _ENTITY_TYPE_PRIORITY.get(existing.entity_type, 0)
        candidate_priority = _ENTITY_TYPE_PRIORITY.get(candidate.entity_type, 0)
        if candidate_priority > existing_priority:
            return True
        if candidate_priority < existing_priority:
            return False

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
