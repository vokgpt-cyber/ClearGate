"""GLiNER-based zero-shot entity recognition adapter.

GLiNER detects custom entity types without retraining — you provide
a list of labels and it finds matching spans in text. This is used
as part of Layer 2 in the NER pipeline for entity types that
spaCy's ru_core_news_lg does not cover (e.g., job titles, contract sums).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.entities import DetectedEntity

logger = structlog.get_logger(__name__)

# Label mapping: GLiNER label → VELUM entity type
_LABEL_MAP: dict[str, str] = {
    "person": "PER",
    "organization": "ORG",
    "location": "LOC",
    "address": "ADDR",
    "money": "MON",
    "date": "DATE",
    "position": "POSITION",
    "должность": "POSITION",
    "сумма контракта": "MON",
    "наименование суда": "ORG",
    "кодовое название проекта": "PROJECT_CODENAME",
}


class GLiNERRecognizer:
    """Zero-shot custom entity recognition via GLiNER.

    Args:
        model_name: HuggingFace model identifier for GLiNER.

    Examples:
        >>> recognizer = GLiNERRecognizer("urchade/gliner_medium-v2.1")
        >>> entities = await recognizer.detect(text, labels=["должность", "сумма контракта"])
    """

    def __init__(self, model_name: str = "urchade/gliner_medium-v2.1") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load_model(self) -> None:
        """Lazy-load the GLiNER model on first use."""
        if self._model is None:
            from gliner import GLiNER

            logger.info("gliner.loading", model=self.model_name)
            self._model = GLiNER.from_pretrained(self.model_name)
            logger.info("gliner.loaded", model=self.model_name)

    async def detect(
        self,
        text: str,
        labels: list[str],
        threshold: float = 0.5,
    ) -> list[DetectedEntity]:
        """Detect custom entities by zero-shot labels.

        Args:
            text: Input text to analyze.
            labels: Entity type labels for GLiNER to look for.
            threshold: Minimum confidence score to include a result.

        Returns:
            List of detected entities with type, position, and score.
        """
        self._load_model()
        results = await asyncio.to_thread(
            self._model.predict_entities, text, labels, threshold=threshold
        )

        entities = []
        for r in results:
            entity_type = _LABEL_MAP.get(r["label"].lower(), r["label"].upper())
            entities.append(
                DetectedEntity(
                    text=r["text"],
                    entity_type=entity_type,
                    start=r["start"],
                    end=r["end"],
                    score=r["score"],
                    source_layer="ner",
                    metadata={"gliner_label": r["label"]},
                )
            )

        logger.info("gliner.detected", count=len(entities))
        return entities
