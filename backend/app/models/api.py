"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import DetectedEntity


class CreateSessionRequest(BaseModel):
    """Request to create a new anonymization session."""

    locale: Literal["ru", "en"] = "ru"
    enable_llm_layer: bool = False  # False by default for Alpha (no GPU requirement)
    custom_entities: list[str] = Field(default_factory=list)


class CreateSessionResponse(BaseModel):
    """Response from session creation."""

    session_id: str
    created_at: str
    expires_at: str


class SessionInfoResponse(BaseModel):
    """Session state information (no mapping exposed)."""

    session_id: str
    created_at: str
    entity_count: int
    locale: str


class UploadResponse(BaseModel):
    """Response from document upload/parse.

    When a DOCX is uploaded with a ``session_id`` query parameter, the raw
    bytes are stored inside the session and ``document_id`` is populated
    (equal to the session id). The frontend uses this to fetch the raw
    bytes back via ``GET /api/documents/{document_id}/raw`` and render the
    file with Word-like fidelity using docx-preview.
    """

    text: str
    format: Literal["docx", "pdf", "txt"]
    page_count: int | None = None
    char_count: int
    document_id: str | None = None


class ParseTextRequest(BaseModel):
    """Request to submit plain text directly."""

    text: str = Field(..., min_length=1, max_length=10_000_000)


class AnonymizeRequest(BaseModel):
    """Request to run anonymization on text."""

    text: str = Field(..., min_length=1, max_length=10_000_000)


class DeepScanEntity(DetectedEntity):
    """Deep-scan entity payload from the interactive UI.

    The frontend's interactive entities carry convenience fields such as
    ``id`` and ``state`` at the top level. Ignore them here and preserve
    durable values through ``metadata``.
    """

    model_config = ConfigDict(extra="ignore")


class DeepScanRequest(AnonymizeRequest):
    """Request to run optional local-LLM verification over current entities."""

    entities: list[DeepScanEntity] = Field(default_factory=list)


class AnonymizeResponse(BaseModel):
    """Response from anonymization."""

    anonymized_text: str
    entities: list[DetectedEntity]
    stats: dict[str, int]


class DeanonymizeRequest(BaseModel):
    """Request to deanonymize text using session registry."""

    text: str


class DeanonymizeResponse(BaseModel):
    """Response from deanonymization."""

    text: str


class UpdateEntityRequest(BaseModel):
    """Request to update an entity (accept/reject/edit)."""

    action: Literal["accept", "reject", "edit"]
    new_value: str | None = None


class AddEntityRequest(BaseModel):
    """Request to manually register a custom entity.

    Sent by the UI when the user selects text in the original panel and
    picks an entity type. The backend assigns a consistent placeholder
    via :class:`EntityRegistry` and returns a stable id.
    """

    text: str = Field(..., min_length=1, max_length=4096)
    entity_type: str = Field(..., min_length=1, max_length=64)
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)


class AddEntityResponse(BaseModel):
    """Response from manually adding a custom entity."""

    id: str
    placeholder: str
    entity: DetectedEntity



# ── Deanonymization (Phase 1 round-trip) ──────────────────────────


class ImportResponseResult(BaseModel):
    """Response from importing an LLM-response .docx for deanonymization."""

    text: str
    char_count: int
    placeholder_count: int = Field(
        default=0,
        description="Number of placeholder-like patterns detected in the text",
    )


class UnresolvedPlaceholder(BaseModel):
    """A placeholder found in the response that has no match in the registry."""

    raw_text: str = Field(description="Exact text as it appears in the document")
    normalized: str = Field(description="Normalized form attempted for lookup")
    paragraph_index: int = Field(
        default=0,
        description="0-based index of the paragraph where the placeholder was found",
    )


class Restoration(BaseModel):
    """A single placeholder that was successfully substituted with its real value.

    Returned so the frontend can render interactive overlays on top of the
    deanonymized preview, reusing the same entity-overlay UI as the
    anonymization pane.
    """

    placeholder: str = Field(description="Normalized placeholder, e.g. [ЛИЦО_1]")
    real_value: str = Field(description="Text that was substituted in")
    entity_type: str = Field(description="Entity type, e.g. PER, ORG, RU_INN")
    paragraph_index: int = Field(default=0)


class DeanonymizeDocxResult(BaseModel):
    """Response from DOCX deanonymization."""

    unresolved: list[UnresolvedPlaceholder] = Field(default_factory=list)
    restorations: list[Restoration] = Field(default_factory=list)
    total_replacements: int = 0
    total_unresolved: int = 0


class ManualResolution(BaseModel):
    """A user-supplied value for an unresolved placeholder."""

    placeholder: str = Field(description="The normalized placeholder, e.g. [ЛИЦО_5]")
    value: str = Field(description="The real value to substitute")


class ExportDeanonymizedRequest(BaseModel):
    """Body for the deanonymized-DOCX export endpoint."""

    manual_resolutions: list[ManualResolution] = Field(default_factory=list)
