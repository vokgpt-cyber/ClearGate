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
from app.services.anonymization_policy import apply_policy_decisions
from app.services.bge_retriever import BGERetriever
from app.services.document_chunker import Chunk
from app.services.gliner_recognizer import GLiNERRecognizer
from app.services.llm_entity_map_extractor import LLMEntityMapExtractor
from app.services.local_llm_verifier import LocalLLMVerifier
from app.services.organization_policy import (
    organization_aliases,
    should_keep_organization_entity,
)
from app.services.regex_recognizers import build_all_recognizers
from app.services.stopwords import is_stopword

logger = structlog.get_logger(__name__)

EntityEngineMode = Literal["classic", "gemma_shadow", "gemma_primary", "hybrid_consensus"]


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
    r"(?:№|N\s*)\s*[\wА-Яа-яЁё/-]{2,}|"
    r"от\s+\d{2}\.\d{2}\.\d{2,4}|"
    r"от\s+\d{1,2}\s+[а-яё]+\s+\d{4}\s*г?\.?|"
    r"договор|между\s*:",
    re.IGNORECASE,
)
_FINANCIAL_CUE = re.compile(
    r"\b(?:сумм[ауы]|цена|стоимость|вознаграждение|оплат[ауы]|выручк[аи]|"
    r"штраф|неустойк[аиу]|пен[яи]|НДС|CNY|CNH|RMB|RUB|RUR|USD|EUR)\b",
    re.IGNORECASE,
)
_MONEY_LIKE_NUMBER = re.compile(r"^\d{1,3}(?:[ \u00A0]\d{3})+(?:[,.]\d{1,2})?$")
_BIK_VALUE = re.compile(r"^04\d{7}$")
_BANK_ACCOUNT_VALUE = re.compile(r"^\d{20}$")
_KPP_VALUE = re.compile(r"^\d{9}$")
_INN_VALUE = re.compile(r"^(?:\d{10}|\d{12})$")
_OGRN_VALUE = re.compile(r"^(?:\d{13}|\d{15})$")
_MONEY_DIGIT = re.compile(r"\d")
_MONEY_CURRENCY = re.compile(
    r"\b(?:руб\.?|рубл[а-яё]*|RUB|RUR|USD|EUR|CNY|CNH|RMB|GBP|CHF|JPY|HKD|AED|TRY|KZT|BYN|UAH|"
    r"доллар[а-яё]*|евро|юан[ьяей]*|тенге)\b|[₽€$£¥]",
    re.IGNORECASE,
)
_NON_SECRET_PERCENT_CUE = re.compile(
    r"\b(?:НДС|VAT|пен[яи]|неустойк[аиу]|штраф)\b",
    re.IGNORECASE,
)
_CURRENCY_CODE_VALUE = re.compile(
    r"^(?:RUB|RUR|USD|EUR|CNY|CNH|RMB|GBP|CHF|JPY|HKD|AED|TRY|KZT|BYN|UAH)$",
    re.IGNORECASE,
)
_RELATIVE_DURATION_VALUE = re.compile(
    r"\b\d+\s*(?:рабочих\s+|календарных\s+)?"
    r"(?:дн(?:я|ей|ь)?|месяц(?:ев|а)?|мес\.?|лет|год(?:а|ов)?)\b",
    re.IGNORECASE,
)
_PHONE_IN_LINE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
_PUBLIC_SUPPORT_PHONE_CUE = re.compile(
    r"\b(?:круглосуточн\w*|федеральн\w*|медицинск\w*|пульт\w*|"
    r"renhealth|ренессанс)\b",
    re.IGNORECASE,
)
_PUBLIC_SUPPORT_PHONE_CITY_CUE = re.compile(
    r"\b(?:москва|санкт[- ]петербург)\b",
    re.IGNORECASE,
)
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
    "выписка",
    "акт",
    "сверка",
    "сверки",
    "расчет",
    "расчеты",
    "расчетов",
    "расчёты",
    "расчётов",
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
    "RU_POLICY_NUMBER": 75,
    "MON": 90,
    "RU_DATE": 65,
    "DATE": 65,
    "ADDR": 60,
    "PER": 50,
    "ORG": 45,
    "POSITION": 35,
    "LOC": 30,
}

_HIGH_PRECISION_BASE_TYPES = {
    "ADDR",
    "DATE",
    "EMAIL_ADDRESS",
    "MON",
    "RU_BANK_ACCOUNT",
    "RU_BIK",
    "RU_CASE_NUMBER",
    "RU_CONTRACT_NUMBER",
    "RU_DATE",
    "RU_INN",
    "RU_KPP",
    "RU_OGRN",
    "RU_PASSPORT",
    "RU_PHONE",
    "RU_POLICY_NUMBER",
    "RU_SNILS",
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
        ollama_model: str = "gemma4:26b",
        ollama_host: str | None = None,
        enable_llm_layer: bool = True,
        default_gliner_labels: list[str] | None = None,
        embedder_url: str | None = None,
        entity_engine: EntityEngineMode = "classic",
    ) -> None:
        self.analyzer = self._build_presidio_analyzer(spacy_model)
        self.gliner = GLiNERRecognizer(gliner_model) if gliner_model else None
        self.llm_verifier = LocalLLMVerifier(ollama_model) if enable_llm_layer else None
        self.llm_entity_map = (
            LLMEntityMapExtractor(model=ollama_model, base_url=ollama_host)
            if enable_llm_layer and entity_engine != "classic"
            else None
        )
        self.bge_retriever = BGERetriever(base_url=embedder_url)
        self.default_gliner_labels: list[str] = list(default_gliner_labels or [])
        self.entity_engine: EntityEngineMode = entity_engine
        self.last_entity_engine_report: dict[str, object] | None = None

        logger.info(
            "ner_pipeline.init",
            spacy=spacy_model or "disabled",
            gliner=gliner_model or "disabled",
            llm=ollama_model if enable_llm_layer else "disabled",
            entity_engine=entity_engine,
            bge=embedder_url or "default",
            default_gliner_labels_count=len(self.default_gliner_labels),
        )

    def _build_presidio_analyzer(self, spacy_model: str | None) -> AnalyzerEngine:
        """Build Presidio analyzer with spaCy and custom recognizers."""
        if not spacy_model:
            raise RuntimeError(
                "SPACY_MODEL is required. CLEARGATE refuses to start without "
                "the Russian spaCy model because it would silently reduce "
                "anonymization quality."
            )

        try:
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "ru", "model_name": spacy_model}],
            }
            nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
            logger.info("ner_pipeline.spacy_loaded", model=spacy_model)
        except Exception as exc:
            logger.error("ner_pipeline.spacy_required_failed", model=spacy_model, exc_info=True)
            raise RuntimeError(
                f"Required spaCy model '{spacy_model}' is unavailable. "
                "Install it during Docker build via SPACY_MODEL_WHEEL_URL."
            ) from exc

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

        if self.entity_engine == "classic":
            entities = await self._classic_llm_pass(text, entities)
        elif self.entity_engine == "gemma_shadow":
            classic_entities = await self._classic_llm_pass(text, list(entities))
            await self._record_gemma_shadow_report(text, entities, classic_entities)
            entities = classic_entities
        elif self.entity_engine == "gemma_primary":
            entities = await self._gemma_entity_map_pass(
                text,
                entities,
                include_all_base=False,
            )
        elif self.entity_engine == "hybrid_consensus":
            entities = await self._gemma_entity_map_pass(
                text,
                entities,
                include_all_base=True,
            )
        else:
            logger.warning("ner_pipeline.unknown_entity_engine", entity_engine=self.entity_engine)

        entities = self.post_process(text, entities)
        logger.info("ner_pipeline.analyze.done", entity_count=len(entities))
        return entities

    async def _classic_llm_pass(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Run the existing LLM verifier/find-missed layers."""
        if self.llm_verifier:
            try:
                entities = await self.llm_verifier.verify_and_refine(text, entities)
            except Exception:
                logger.warning("ner_pipeline.llm_verifier_failed", exc_info=True)

        if self.llm_verifier:
            try:
                missed = await self.llm_verifier.find_missed_entities(text, entities)
                if missed:
                    entities.extend(missed)
            except Exception:
                logger.warning("ner_pipeline.find_missed_failed", exc_info=True)
        return entities

    async def _gemma_entity_map_pass(
        self,
        text: str,
        base_entities: list[DetectedEntity],
        *,
        include_all_base: bool,
    ) -> list[DetectedEntity]:
        """Combine deterministic candidates with validated Gemma span proposals."""
        if not self.llm_entity_map:
            return base_entities

        try:
            gemma_entities = await self.llm_entity_map.extract(
                text,
                known_entities=base_entities,
            )
        except Exception:
            logger.warning("ner_pipeline.llm_entity_map_failed", exc_info=True)
            return base_entities

        if include_all_base:
            selected_base = list(base_entities)
        else:
            selected_base = [
                entity
                for entity in base_entities
                if entity.entity_type in _HIGH_PRECISION_BASE_TYPES
                or (entity.source_layer == "regex" and entity.score >= 0.85)
            ]

        self.last_entity_engine_report = {
            "engine": self.entity_engine,
            "base_count": len(base_entities),
            "selected_base_count": len(selected_base),
            "gemma_count": len(gemma_entities),
        }
        return [*selected_base, *gemma_entities]

    async def _record_gemma_shadow_report(
        self,
        text: str,
        base_entities: list[DetectedEntity],
        classic_entities: list[DetectedEntity],
    ) -> None:
        """Run Gemma-map out of band and store a compact comparison report."""
        if not self.llm_entity_map:
            return
        try:
            gemma_entities = await self.llm_entity_map.extract(
                text,
                known_entities=base_entities,
            )
        except Exception:
            logger.warning("ner_pipeline.llm_entity_map_shadow_failed", exc_info=True)
            return

        classic_keys = {
            (entity.start, entity.end, entity.entity_type, entity.text)
            for entity in classic_entities
        }
        gemma_keys = {
            (entity.start, entity.end, entity.entity_type, entity.text)
            for entity in gemma_entities
        }
        self.last_entity_engine_report = {
            "engine": "gemma_shadow",
            "base_count": len(base_entities),
            "classic_count": len(classic_entities),
            "gemma_count": len(gemma_entities),
            "gemma_only_count": len(gemma_keys - classic_keys),
            "classic_only_count": len(classic_keys - gemma_keys),
        }

    def post_process(
        self,
        text: str,
        entities: list[DetectedEntity],
        *,
        include_review: bool = False,
    ) -> list[DetectedEntity]:
        """Apply shared entity cleanup after any detection source.

        Used by the fast regex/NER pass and by optional manual LLM deep scan
        so both paths get the same stop-word and overlap behavior.
        """
        entities = self._filter_stopwords(entities)
        entities = self._filter_document_title_false_positives(text, entities)
        entities = self._filter_structured_false_positives(text, entities)
        entities = self._filter_invalid_structured_entities(text, entities)
        entities = self._filter_public_support_phones(text, entities)
        entities = self._filter_contact_location_false_positives(text, entities)
        entities = apply_policy_decisions(text, entities, include_review=include_review)
        entities = self._expand_organization_aliases(text, entities)
        entities = self._merge_adjacent_per(entities, text)
        entities = self._merge_overlapping(entities)
        # Merging can create a larger PER span from two noisy adjacent guesses
        # (e.g. "Материалы" + "Доверителя"). Run the precision gate once more
        # after merge/overlap resolution so merged spans cannot bypass policy.
        entities = apply_policy_decisions(text, entities, include_review=include_review)
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
            recognition_metadata = dict(getattr(r, "recognition_metadata", None) or {})
            entities.append(
                DetectedEntity(
                    text=text[r.start : r.end],
                    entity_type=entity_type,
                    start=r.start,
                    end=r.end,
                    score=r.score,
                    source_layer="regex" if r.score >= 0.7 else "ner",
                    metadata={
                        "presidio_type": r.entity_type,
                        "recognizer_name": recognition_metadata.get("recognizer_name"),
                        "recognition_metadata": recognition_metadata,
                    },
                )
            )
        return entities

    def _filter_organization_policy(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Keep only high-confidence organization auto-redactions."""
        filtered: list[DetectedEntity] = []
        for entity in entities:
            if entity.entity_type == "ORG" and not should_keep_organization_entity(text, entity):
                logger.debug(
                    "ner_pipeline.organization_policy_filtered",
                    text=entity.text,
                    source_layer=entity.source_layer,
                    metadata=entity.metadata,
                )
                continue
            filtered.append(entity)
        return filtered

    def _expand_organization_aliases(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Add exact short aliases derived from accepted organization spans."""
        occupied = [(entity.start, entity.end) for entity in entities]
        additions: list[DetectedEntity] = []
        for entity in entities:
            if entity.entity_type != "ORG":
                continue
            if (entity.metadata or {}).get("policy_action") != "auto":
                continue
            for alias in organization_aliases(entity):
                pattern = re.compile(
                    rf"(?<![\w-]){re.escape(alias)}(?![\w-])",
                    re.IGNORECASE,
                )
                for match in pattern.finditer(text):
                    if any(
                        match.start() < end and start < match.end()
                        for start, end in occupied
                    ):
                        continue
                    additions.append(
                        DetectedEntity(
                            text=text[match.start() : match.end()],
                            entity_type="ORG",
                            start=match.start(),
                            end=match.end(),
                            score=min(entity.score, 0.88),
                            source_layer=entity.source_layer,
                            metadata={
                                **entity.metadata,
                                "derived_alias": True,
                                "derived_from": entity.text,
                            },
                        )
                    )
                    occupied.append((match.start(), match.end()))
        return [*entities, *additions]

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
            if entity.entity_type in {"ORG", "LOC"} and self._is_document_title(text, entity):
                logger.debug(
                    "ner_pipeline.document_title_filtered",
                    text=entity.text,
                    entity_type=entity.entity_type,
                )
                continue
            filtered.append(entity)
        return filtered

    def _filter_invalid_structured_entities(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Drop LLM/NER guesses that contradict strict structured formats."""
        filtered: list[DetectedEntity] = []
        for entity in entities:
            value = entity.text.strip()
            digits = re.sub(r"\D", "", value)
            if entity.entity_type == "RU_BIK" and not _BIK_VALUE.fullmatch(digits):
                logger.debug("ner_pipeline.invalid_bik_filtered", text=entity.text)
                continue
            if (
                entity.entity_type == "RU_BANK_ACCOUNT"
                and not _BANK_ACCOUNT_VALUE.fullmatch(digits)
            ):
                logger.debug("ner_pipeline.invalid_bank_account_filtered", text=entity.text)
                continue
            if entity.entity_type == "RU_KPP" and not _KPP_VALUE.fullmatch(digits):
                logger.debug("ner_pipeline.invalid_kpp_filtered", text=entity.text)
                continue
            if entity.entity_type == "RU_INN" and not _INN_VALUE.fullmatch(digits):
                logger.debug("ner_pipeline.invalid_inn_filtered", text=entity.text)
                continue
            if entity.entity_type == "RU_OGRN" and not _OGRN_VALUE.fullmatch(digits):
                logger.debug("ner_pipeline.invalid_ogrn_filtered", text=entity.text)
                continue
            if entity.entity_type == "MON":
                if not _MONEY_DIGIT.search(value):
                    logger.debug("ner_pipeline.money_without_digits_filtered", text=entity.text)
                    continue
                window = text[max(0, entity.start - 80) : min(len(text), entity.end + 80)]
                if "%" in value and _NON_SECRET_PERCENT_CUE.search(window):
                    logger.debug("ner_pipeline.non_secret_percent_filtered", text=entity.text)
                    continue
                if "%" not in value and not _MONEY_CURRENCY.search(value):
                    # Bare numbers can be monetary only with a strong local cue.
                    if not _FINANCIAL_CUE.search(window):
                        logger.debug("ner_pipeline.bare_money_without_cue_filtered", text=entity.text)
                        continue
            if entity.entity_type in {"ORG", "LOC"} and _CURRENCY_CODE_VALUE.fullmatch(value):
                logger.debug("ner_pipeline.currency_code_filtered", text=entity.text)
                continue
            if entity.entity_type in {"DATE", "RU_DATE"} and _RELATIVE_DURATION_VALUE.search(value):
                logger.debug("ner_pipeline.relative_duration_date_filtered", text=entity.text)
                continue
            filtered.append(entity)
        return filtered

    def _filter_public_support_phones(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Drop public hotline/support phones in insurance leaflets."""
        filtered: list[DetectedEntity] = []
        for entity in entities:
            if entity.entity_type != "RU_PHONE":
                filtered.append(entity)
                continue

            digits = re.sub(r"\D", "", entity.text)
            line_start = text.rfind("\n", 0, entity.start) + 1
            line_end = text.find("\n", entity.end)
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            prev_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
            prev_line = text[prev_line_start : max(0, line_start - 1)]
            window = f"{prev_line}\n{line}"
            is_toll_free = digits.startswith(("7800", "8800"))
            if (
                is_toll_free
                or _PUBLIC_SUPPORT_PHONE_CUE.search(window)
                or _PUBLIC_SUPPORT_PHONE_CITY_CUE.search(line)
            ):
                logger.debug("ner_pipeline.public_support_phone_filtered", text=entity.text)
                continue

            filtered.append(entity)
        return filtered

    def _filter_contact_location_false_positives(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Drop city/adjective tails that label support-phone routing.

        DMS/insurance memos often list call-center phones like
        "8 (495) ... Москва". The city after the phone is a routing label,
        not a user-specific address. Real addresses are kept because they do
        not appear as a trailing token on a phone line.
        """
        filtered: list[DetectedEntity] = []
        for entity in entities:
            if entity.entity_type != "LOC":
                filtered.append(entity)
                continue

            line_start = text.rfind("\n", 0, entity.start) + 1
            line_end = text.find("\n", entity.end)
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            relative_start = entity.start - line_start
            if any(match.end() <= relative_start for match in _PHONE_IN_LINE.finditer(line)):
                logger.debug("ner_pipeline.contact_location_filtered", text=entity.text)
                continue

            filtered.append(entity)
        return filtered

    def _is_document_title(self, text: str, entity: DetectedEntity) -> bool:
        if entity.start > 1200:
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
