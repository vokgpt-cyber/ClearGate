"""Golden corpus regression tests for synthetic legal documents.

The files in ``tests/fixtures/golden`` are safe synthetic contracts. Each
``*.expected.json`` file points at a sibling ``*.txt`` source and declares:

* expected_entities: spans which must be detected with the declared type;
* forbidden_entities: spans which must not be detected as the declared type;
* expected_type_counts: coarse count bounds for important entity types;
* llm_false_positives: simulated LLM additions that post-processing must drop.

This keeps hard-won anonymization fixes executable instead of relying on
manual screenshots and memory.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

import pytest

from app.models.entities import DetectedEntity
from app.services.ner_pipeline import NERPipeline

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden"


def _load_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(GOLDEN_DIR.glob("*.expected.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec["_expected_path"] = str(path)
        spec["_text"] = (GOLDEN_DIR / spec["text_file"]).read_text(encoding="utf-8")
        specs.append(spec)
    return specs


GOLDEN_SPECS = _load_specs()


@pytest.fixture(scope="module")
def pipeline():
    return NERPipeline(
        spacy_model="ru_core_news_sm",
        gliner_model=None,
        enable_llm_layer=False,
    )


def _matches(entity: DetectedEntity, expected: dict[str, str]) -> bool:
    if entity.entity_type != expected["entity_type"]:
        return False
    return entity.text == expected["text"]


def _format_entities(entities: list[DetectedEntity]) -> list[str]:
    return [
        f"{entity.entity_type}:{entity.text}@{entity.start}-{entity.end}"
        for entity in entities
    ]


@pytest.mark.asyncio
@pytest.mark.golden
@pytest.mark.parametrize("spec", GOLDEN_SPECS, ids=[s["id"] for s in GOLDEN_SPECS])
async def test_golden_expected_entities(pipeline, spec):
    entities = await pipeline.analyze(spec["_text"])

    for expected in spec["expected_entities"]:
        assert any(_matches(entity, expected) for entity in entities), (
            f"{spec['id']}: expected {expected['entity_type']}:{expected['text']!r} "
            f"not found. Found: {_format_entities(entities)}"
        )


@pytest.mark.asyncio
@pytest.mark.golden
@pytest.mark.parametrize("spec", GOLDEN_SPECS, ids=[s["id"] for s in GOLDEN_SPECS])
async def test_golden_forbidden_entities(pipeline, spec):
    entities = await pipeline.analyze(spec["_text"])

    for forbidden in spec.get("forbidden_entities", []):
        assert not any(_matches(entity, forbidden) for entity in entities), (
            f"{spec['id']}: forbidden {forbidden['entity_type']}:{forbidden['text']!r} "
            f"was detected. Found: {_format_entities(entities)}"
        )


@pytest.mark.asyncio
@pytest.mark.golden
@pytest.mark.parametrize("spec", GOLDEN_SPECS, ids=[s["id"] for s in GOLDEN_SPECS])
async def test_golden_type_count_bounds(pipeline, spec):
    entities = await pipeline.analyze(spec["_text"])
    counts = Counter(entity.entity_type for entity in entities)

    for entity_type, bounds in spec.get("expected_type_counts", {}).items():
        if "min" in bounds:
            assert counts[entity_type] >= bounds["min"], (
                f"{spec['id']}: {entity_type} count {counts[entity_type]} "
                f"is below {bounds['min']}. Found: {_format_entities(entities)}"
            )
        if "max" in bounds:
            assert counts[entity_type] <= bounds["max"], (
                f"{spec['id']}: {entity_type} count {counts[entity_type]} "
                f"is above {bounds['max']}. Found: {_format_entities(entities)}"
            )


@pytest.mark.asyncio
@pytest.mark.golden
@pytest.mark.parametrize(
    "spec",
    [s for s in GOLDEN_SPECS if s.get("llm_false_positives")],
    ids=[s["id"] for s in GOLDEN_SPECS if s.get("llm_false_positives")],
)
async def test_golden_llm_false_positives_do_not_degrade_result(pipeline, spec):
    text = spec["_text"]
    entities = await pipeline.analyze(text)
    noisy_entities = list(entities)

    for false_positive in spec["llm_false_positives"]:
        start = text.index(false_positive["text"])
        noisy_entities.append(
            DetectedEntity(
                text=false_positive["text"],
                entity_type=false_positive["entity_type"],
                start=start,
                end=start + len(false_positive["text"]),
                score=false_positive.get("score", 0.8),
                source_layer="llm-scan",
            )
        )

    processed = pipeline.post_process(text, noisy_entities)
    for false_positive in spec["llm_false_positives"]:
        assert not any(_matches(entity, false_positive) for entity in processed), (
            f"{spec['id']}: LLM false positive survived post-process: "
            f"{false_positive['entity_type']}:{false_positive['text']!r}. "
            f"Found: {_format_entities(processed)}"
        )
