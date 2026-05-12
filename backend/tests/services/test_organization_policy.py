"""Precision tests for automatic ORG acceptance."""

from __future__ import annotations

from app.models.entities import DetectedEntity
from app.services.organization_policy import organization_aliases, should_keep_organization_entity


def _org(
    text: str,
    source_layer: str = "ner",
    score: float = 0.88,
    metadata: dict | None = None,
    haystack: str | None = None,
) -> tuple[str, DetectedEntity]:
    source = haystack or text
    start = source.index(text)
    return source, DetectedEntity(
        text=text,
        entity_type="ORG",
        start=start,
        end=start + len(text),
        score=score,
        source_layer=source_layer,
        metadata=metadata or {},
    )


def test_generic_professional_form_is_not_auto_org() -> None:
    text, entity = _org(
        "Адвокатское бюро",
        metadata={"gliner_label": "organization"},
    )

    assert not should_keep_organization_entity(text, entity)


def test_professional_firm_with_distinctive_name_is_auto_org() -> None:
    text, entity = _org(
        "Адвокатское бюро ЕПАМ",
        metadata={"gliner_label": "organization"},
    )

    assert should_keep_organization_entity(text, entity)


def test_professional_firm_genitive_with_distinctive_name_is_auto_org() -> None:
    text, entity = _org(
        "Адвокатского Бюро ЕПАМ",
        metadata={"gliner_label": "organization"},
    )

    assert should_keep_organization_entity(text, entity)


def test_generic_professional_form_genitive_is_not_auto_org() -> None:
    text, entity = _org(
        "Адвокатского Бюро",
        metadata={"gliner_label": "organization"},
    )

    assert not should_keep_organization_entity(text, entity)


def test_short_name_after_professional_form_is_auto_org() -> None:
    text, entity = _org(
        "ЕПАМ",
        haystack="Документ подготовило Адвокатское бюро ЕПАМ.",
        metadata={"gliner_label": "organization"},
    )

    assert should_keep_organization_entity(text, entity)


def test_product_like_name_without_legal_context_is_not_auto_org() -> None:
    text, entity = _org(
        "Alice AI",
        metadata={"gliner_label": "organization"},
    )

    assert not should_keep_organization_entity(text, entity)


def test_english_legal_entity_suffix_is_auto_org() -> None:
    text, entity = _org(
        "EPAM Systems, Inc.",
        metadata={"gliner_label": "organization"},
    )

    assert should_keep_organization_entity(text, entity)


def test_strict_regex_organization_recognizer_is_auto_org() -> None:
    text, entity = _org(
        "АО «Норд-Хим»",
        source_layer="regex",
        score=0.94,
        metadata={"recognizer_name": "Russian Organization Recognizer"},
    )

    assert should_keep_organization_entity(text, entity)


def test_safe_aliases_are_derived_from_accepted_orgs() -> None:
    _, quoted = _org(
        "АО «Норд-Хим»",
        source_layer="regex",
        score=0.94,
        metadata={"recognizer_name": "Russian Organization Recognizer"},
    )
    _, professional = _org(
        "Адвокатское бюро ЕПАМ",
        metadata={"gliner_label": "organization"},
    )

    assert organization_aliases(quoted) == ["Норд-Хим"]
    assert organization_aliases(professional) == ["ЕПАМ"]
