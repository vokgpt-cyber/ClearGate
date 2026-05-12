"""Policy layer for deciding which detected spans are auto-redacted.

Recognizers intentionally cast a wide net. This module is the precision gate:
it classifies the document, turns raw candidates into auto/review/ignore
decisions, and records a compact reason for audit/debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from app.models.entities import DetectedEntity
from app.services.organization_policy import should_keep_organization_entity
from app.services.stopwords import is_stopword


DocumentProfile = Literal[
    "insurance",
    "internal_policy",
    "registry_extract",
    "legal_contract",
    "generic",
]

PolicyAction = Literal["auto", "review", "ignore"]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    profile: DocumentProfile


_INSURANCE_PROFILE_RE = re.compile(
    r"\b(?:дмс|полис|застрахован\w*|страхов\w+|медицинск\w+|renhealth)\b",
    re.IGNORECASE,
)
_INTERNAL_POLICY_PROFILE_RE = re.compile(
    r"\b(?:положение|политика|памятка|ии-инструмент\w*|ии-систем\w*|"
    r"адвокатск\w+\s+бюро|сотрудник\w*\s+бюро)\b",
    re.IGNORECASE,
)
_REGISTRY_PROFILE_RE = re.compile(
    r"\b(?:егрюл|единого\s+государственного\s+реестра|огрн|кпп|оквэд)\b",
    re.IGNORECASE,
)
_CONTRACT_PROFILE_RE = re.compile(
    r"\b(?:договор|контракт|соглашение|между|сторон\w*|аренд\w*|"
    r"лизинг|за[её]м|кредит|поставка|подряд|лицензионн\w*)\b",
    re.IGNORECASE,
)

_STRUCTURED_AUTO_TYPES = {
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

_GENERIC_DESCRIPTOR_ROOTS = (
    "адвокатск",
    "бюро",
    "доверител",
    "застрах",
    "инструмент",
    "контрагент",
    "кандидат",
    "клиент",
    "медицинск",
    "настоящ",
    "памятк",
    "пользовател",
    "положени",
    "политик",
    "представител",
    "работник",
    "сотрудник",
    "страхов",
)

_PUBLIC_SERVICE_OR_PRODUCTS = {
    "alice ai",
    "алиса ai",
    "алиса ии",
    "aria",
    "atlas",
    "chatgpt",
    "claude",
    "comet",
    "deepseek",
    "gemini",
    "gigachat",
    "renhealth",
    "реклама",
    "ренессанс здоровье",
    "роспатент",
    "фнс",
}

_FIO_VALUE_RE = re.compile(
    r"^(?:[А-ЯЁ][а-яё-]{1,}|[А-ЯЁ]{2,})"
    r"(?:\s+(?:[А-ЯЁ][а-яё-]{1,}|[А-ЯЁ]{2,}|[А-ЯЁ]\.)){1,2}$"
)
_PERSON_CONTEXT_RE = re.compile(
    r"(?:фио|ф\.?\s*и\.?\s*о\.?|застрахован\w*|пациент|клиент|"
    r"директор|представител\w*|подписант|сотрудник\w*)\W*$",
    re.IGNORECASE,
)
_PUBLIC_PHONE_CONTEXT_RE = re.compile(
    r"\b(?:круглосуточн\w*|федеральн\w*|медицинск\w*|пульт\w*|"
    r"москва|санкт[- ]петербург|renhealth|ренессанс)\b",
    re.IGNORECASE,
)
_LEGAL_FORM_RE = re.compile(
    r"\b(?:ооо|оао|ао|пао|зао|нко|ип|llc|ltd\.?|limited|inc\.?|corp\.?|"
    r"corporation|company|co\.?|gmbh|ag|plc|pte\.?\s+ltd\.?)\b",
    re.IGNORECASE,
)


def detect_document_profile(text: str) -> DocumentProfile:
    """Classify the source text into a coarse profile for policy decisions."""
    head = text[:10_000]
    if _INSURANCE_PROFILE_RE.search(head):
        return "insurance"
    if _INTERNAL_POLICY_PROFILE_RE.search(head):
        return "internal_policy"
    if _REGISTRY_PROFILE_RE.search(head):
        return "registry_extract"
    if _CONTRACT_PROFILE_RE.search(head):
        return "legal_contract"
    return "generic"


def apply_policy_decisions(
    text: str,
    entities: list[DetectedEntity],
    *,
    include_review: bool = False,
) -> list[DetectedEntity]:
    """Filter entities according to the policy and annotate kept spans."""
    profile = detect_document_profile(text)
    result: list[DetectedEntity] = []
    for entity in entities:
        decision = decide_entity(text, entity, profile)
        if decision.action == "ignore":
            continue
        if decision.action == "review" and not include_review:
            continue
        result.append(_with_policy_metadata(entity, decision))
    return result


def decide_entity(
    text: str,
    entity: DetectedEntity,
    profile: DocumentProfile | None = None,
) -> PolicyDecision:
    """Return the policy decision for a single candidate entity."""
    profile = profile or detect_document_profile(text)
    value = _normalize(entity.text)

    if not value:
        return PolicyDecision("ignore", "empty", profile)

    if is_stopword(entity.text, entity.entity_type):
        return PolicyDecision("ignore", "stopword", profile)

    if value in _PUBLIC_SERVICE_OR_PRODUCTS:
        return PolicyDecision("ignore", "public_service_or_product", profile)

    if entity.entity_type in _STRUCTURED_AUTO_TYPES:
        if entity.entity_type == "RU_PHONE" and _looks_like_public_support_phone(text, entity):
            return PolicyDecision("ignore", "public_support_phone", profile)
        return PolicyDecision("auto", "structured_type", profile)

    if entity.entity_type == "ORG":
        return _decide_org(text, entity, profile, value)

    if entity.entity_type == "PER":
        return _decide_person(text, entity, profile, value)

    if entity.entity_type == "LOC":
        return _decide_location(text, entity, profile, value)

    if entity.entity_type == "POSITION":
        return PolicyDecision("review", "position_review_only", profile)

    return PolicyDecision("review", "unknown_type_review_only", profile)


def _decide_org(
    text: str,
    entity: DetectedEntity,
    profile: DocumentProfile,
    value: str,
) -> PolicyDecision:
    if _all_generic_descriptor_tokens(value):
        return PolicyDecision("ignore", "generic_org_descriptor", profile)

    if should_keep_organization_entity(text, entity):
        return PolicyDecision("auto", "strong_organization_signal", profile)

    if profile in {"internal_policy", "insurance"}:
        return PolicyDecision("ignore", "weak_org_in_public_or_policy_text", profile)

    if _LEGAL_FORM_RE.search(value):
        return PolicyDecision("review", "legal_form_without_distinctive_tail", profile)

    return PolicyDecision("review", "weak_organization_candidate", profile)


def _decide_person(
    text: str,
    entity: DetectedEntity,
    profile: DocumentProfile,
    value: str,
) -> PolicyDecision:
    if _all_generic_descriptor_tokens(value):
        return PolicyDecision("ignore", "generic_person_descriptor", profile)

    if _FIO_VALUE_RE.fullmatch(entity.text.strip()):
        return PolicyDecision("auto", "fio_shape", profile)

    before = text[max(0, entity.start - 80) : entity.start]
    if _PERSON_CONTEXT_RE.search(before):
        return PolicyDecision("auto", "person_context", profile)

    # Single-token person guesses in policies and insurance memos are noisy
    # ("Сотрудник", "Пульта", "Страховой"). Only explicit FIO/context survives.
    if profile in {"internal_policy", "insurance"} and len(value.split()) == 1:
        return PolicyDecision("ignore", "weak_single_token_person", profile)

    return PolicyDecision("auto", "person_model_candidate", profile)


def _decide_location(
    text: str,
    entity: DetectedEntity,
    profile: DocumentProfile,
    value: str,
) -> PolicyDecision:
    if _all_generic_descriptor_tokens(value):
        return PolicyDecision("ignore", "generic_location_descriptor", profile)

    if _location_is_phone_tail(text, entity):
        return PolicyDecision("ignore", "phone_routing_location", profile)

    if profile in {"internal_policy", "insurance"}:
        return PolicyDecision("ignore", "weak_location_in_public_or_policy_text", profile)

    return PolicyDecision("auto", "location_model_candidate", profile)


def _with_policy_metadata(
    entity: DetectedEntity,
    decision: PolicyDecision,
) -> DetectedEntity:
    metadata = dict(entity.metadata or {})
    metadata.update(
        {
            "policy_action": decision.action,
            "policy_reason": decision.reason,
            "document_profile": decision.profile,
        }
    )
    return entity.model_copy(update={"metadata": metadata})


def _normalize(value: str) -> str:
    value = value.strip().lower().replace("ё", "е")
    value = value.strip(" \t\r\n:;,.!?-–—()[]{}\"«»")
    return re.sub(r"\s+", " ", value)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9][a-zа-я0-9&.'-]*", value)


def _all_generic_descriptor_tokens(value: str) -> bool:
    tokens = _tokens(value)
    return bool(tokens) and all(
        any(token.startswith(root) for root in _GENERIC_DESCRIPTOR_ROOTS)
        for token in tokens
    )


def _line_window(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    prev_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
    return text[prev_line_start:line_end]


def _looks_like_public_support_phone(text: str, entity: DetectedEntity) -> bool:
    digits = re.sub(r"\D", "", entity.text)
    if digits.startswith(("7800", "8800")):
        return True
    return bool(_PUBLIC_PHONE_CONTEXT_RE.search(_line_window(text, entity.start, entity.end)))


def _location_is_phone_tail(text: str, entity: DetectedEntity) -> bool:
    line = _line_window(text, entity.start, entity.end).splitlines()[-1]
    relative_start = entity.start - (text.rfind("\n", 0, entity.start) + 1)
    phone_re = re.compile(
        r"(?<!\d)(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"
    )
    return any(match.end() <= relative_start for match in phone_re.finditer(line))
