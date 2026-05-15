"""Entity models shared by the anonymization pipeline and API."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


KnownEntityType = Literal[
    "PER",
    "ORG",
    "LOC",
    "ADDR",
    "MON",
    "DATE",
    "RU_INN",
    "RU_OGRN",
    "RU_KPP",
    "RU_SNILS",
    "RU_PASSPORT",
    "RU_BANK_ACCOUNT",
    "RU_BIK",
    "RU_PHONE",
    "RU_DATE",
    "EMAIL_ADDRESS",
    "RU_CASE_NUMBER",
    "RU_CONTRACT_NUMBER",
    "RU_POLICY_NUMBER",
    "POSITION",
    "PROJECT_CODENAME",
]

# Keep entity_type forward-compatible: custom labels can be supplied by users
# and LLM verification may return types added after this release.
EntityType: TypeAlias = str

SourceLayer = Literal["regex", "ner", "llm", "llm-scan", "llm-map", "hybrid"]

KNOWN_ENTITY_TYPES: tuple[str, ...] = (
    "PER",
    "ORG",
    "LOC",
    "ADDR",
    "MON",
    "DATE",
    "RU_INN",
    "RU_OGRN",
    "RU_KPP",
    "RU_SNILS",
    "RU_PASSPORT",
    "RU_BANK_ACCOUNT",
    "RU_BIK",
    "RU_PHONE",
    "RU_DATE",
    "EMAIL_ADDRESS",
    "RU_CASE_NUMBER",
    "RU_CONTRACT_NUMBER",
    "RU_POLICY_NUMBER",
    "POSITION",
    "PROJECT_CODENAME",
)


class DetectedEntity(BaseModel):
    """A single sensitive span detected in source text.

    The text and offsets describe the original document span. ``metadata`` is
    intentionally generic so pipeline layers can attach non-sensitive technical
    details such as placeholder ids, source recognizer names, and UI state.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)
    entity_type: EntityType = Field(..., min_length=1, max_length=64)
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    score: float = Field(..., ge=0.0, le=1.0)
    source_layer: SourceLayer = "regex"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_offsets(self) -> "DetectedEntity":
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self
