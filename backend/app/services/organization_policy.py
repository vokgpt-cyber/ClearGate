"""Precision-first policy for automatically accepted organization entities."""

from __future__ import annotations

import re

from app.models.entities import DetectedEntity


STRICT_ORG_RECOGNIZERS = {
    "Russian Organization Recognizer",
    "English Legal Entity Recognizer",
}

_LEGAL_FORM_RE = re.compile(
    r"\b(?:"
    r"ооо|оао|ао|пао|зао|нко|ип|"
    r"общество\s+с\s+ограниченной\s+ответственностью|"
    r"акционерное\s+общество|"
    r"публичное\s+акционерное\s+общество|"
    r"закрытое\s+акционерное\s+общество|"
    r"индивидуальный\s+предприниматель|"
    r"llc|l\.l\.c\.|ltd\.?|limited|inc\.?|corp\.?|corporation|"
    r"company|co\.?|gmbh|ag|s\.a\.|s\.a\.s\.|b\.v\.|n\.v\.|plc|pte\.?\s+ltd\.?"
    r")\b",
    re.IGNORECASE,
)

_PROFESSIONAL_FORM_RE = re.compile(
    r"\b(?:"
    r"адвокатское\s+бюро|адвокатская\s+контора|коллегия\s+адвокатов|"
    r"юридическая\s+фирма|юридическое\s+бюро|патентное\s+бюро|law\s+firm"
    r")\b",
    re.IGNORECASE,
)

_QUOTED_ALIAS_RE = re.compile(r"[«\"]([^»\"]{2,120})[»\"]")

_GENERIC_ORG_PHRASES = {
    "адвокатское бюро",
    "адвокатская контора",
    "коллегия адвокатов",
    "юридическая фирма",
    "юридическое бюро",
    "патентное бюро",
    "бюро",
    "компания",
    "организация",
    "общество",
    "банк",
    "реквизиты",
    "реквизиты сторон",
}

_GENERIC_ORG_TOKENS = {
    "адвокатское",
    "адвокатская",
    "адвокатов",
    "бюро",
    "коллегия",
    "юридическая",
    "юридическое",
    "патентное",
    "фирма",
    "law",
    "firm",
    "компания",
    "организация",
    "общество",
    "ответственностью",
    "ограниченной",
    "акционерное",
    "публичное",
    "закрытое",
    "индивидуальный",
    "предприниматель",
    "банк",
    "реквизиты",
    "сторон",
    "ооо",
    "оао",
    "ао",
    "пао",
    "зао",
    "нко",
    "ип",
    "llc",
    "ltd",
    "limited",
    "inc",
    "corp",
    "corporation",
    "company",
    "co",
    "gmbh",
    "ag",
    "plc",
}


def should_keep_organization_entity(text: str, entity: DetectedEntity) -> bool:
    """Return whether an ORG span is strong enough for auto-anonymization.

    Broad NER/LLM organization guesses are intentionally treated as weak.
    The base pipeline should auto-redact legal entities and professional-firm
    names with a distinctive tail, not generic descriptors such as
    "Адвокатское бюро" or product-like names such as "Alice AI".
    """
    if entity.entity_type != "ORG":
        return True

    value = entity.text.strip()
    normalized = _normalize(value)
    if not normalized:
        return False

    if _is_generic_org_text(normalized):
        return False

    if _recognizer_name(entity) in STRICT_ORG_RECOGNIZERS:
        return True

    if _LEGAL_FORM_RE.search(normalized) and _has_distinctive_tail(normalized):
        return True

    if _PROFESSIONAL_FORM_RE.search(normalized):
        return _has_professional_name_tail(normalized)

    if _has_professional_context_before(text, entity) and _is_distinctive_short_name(value):
        return True

    # GLiNER/spaCy/LLM guesses without a legal or professional-form signal are
    # useful as review suggestions, but too noisy for automatic redaction.
    if entity.source_layer in {"ner", "llm", "llm-scan"}:
        return False

    return False


def organization_aliases(entity: DetectedEntity) -> list[str]:
    """Return safe short aliases derived from an already accepted ORG span."""
    if entity.entity_type != "ORG":
        return []

    aliases: list[str] = []
    for match in _QUOTED_ALIAS_RE.finditer(entity.text):
        aliases.append(match.group(1).strip())

    professional_match = _PROFESSIONAL_FORM_RE.search(entity.text)
    if professional_match:
        tail = entity.text[professional_match.end() :].strip(" \t\r\n:;,.!?-–—()[]{}\"«»")
        aliases.append(tail)

    result: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = _normalize(alias)
        if not normalized or normalized in seen:
            continue
        if alias.strip() == entity.text.strip():
            continue
        if not _is_distinctive_short_name(alias):
            continue
        seen.add(normalized)
        result.append(alias)
    return result


def _recognizer_name(entity: DetectedEntity) -> str | None:
    metadata = entity.metadata or {}
    name = metadata.get("recognizer_name")
    if isinstance(name, str):
        return name
    nested = metadata.get("recognition_metadata")
    if isinstance(nested, dict):
        nested_name = nested.get("recognizer_name")
        if isinstance(nested_name, str):
            return nested_name
    return None


def _normalize(value: str) -> str:
    value = value.strip().lower().replace("ё", "е")
    value = value.strip(" \t\r\n:;,.!?-–—()[]{}")
    value = value.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", value)


def _is_generic_org_text(normalized: str) -> bool:
    if normalized in _GENERIC_ORG_PHRASES:
        return True
    tokens = _tokens(normalized)
    return bool(tokens) and all(token in _GENERIC_ORG_TOKENS for token in tokens)


def _has_distinctive_tail(normalized: str) -> bool:
    remainder = _LEGAL_FORM_RE.sub(" ", normalized)
    return bool(_distinctive_tokens(remainder))


def _has_professional_name_tail(normalized: str) -> bool:
    match = _PROFESSIONAL_FORM_RE.search(normalized)
    if not match:
        return False
    tail = normalized[match.end() :].strip(" \t\r\n:;,.!?-–—()[]{}\"")
    return bool(_distinctive_tokens(tail))


def _has_professional_context_before(text: str, entity: DetectedEntity) -> bool:
    before = _normalize(text[max(0, entity.start - 80) : entity.start])
    return bool(re.search(r"(?:адвокатское бюро|юридическая фирма|коллегия адвокатов)\s*\"?$", before))


def _is_distinctive_short_name(value: str) -> bool:
    normalized = _normalize(value)
    if _is_generic_org_text(normalized):
        return False
    tokens = _distinctive_tokens(normalized)
    if not tokens:
        return False
    compact = re.sub(r"[^A-Za-zА-Яа-яЁё0-9]", "", value)
    if compact.isupper() and len(compact) >= 3:
        return True
    return any(len(token) >= 4 for token in tokens)


def _distinctive_tokens(value: str) -> list[str]:
    stripped = _PROFESSIONAL_FORM_RE.sub(" ", value)
    stripped = _LEGAL_FORM_RE.sub(" ", stripped)
    return [
        token
        for token in _tokens(stripped)
        if len(token) >= 2 and token not in _GENERIC_ORG_TOKENS
    ]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9][a-zа-я0-9&.'-]*", value)
