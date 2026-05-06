"""Tests for public API request/response models."""

from app.models.api import DeepScanRequest
from app.routers.documents import DeanonymizeRequest
from app.services.local_llm_verifier import _normalize_entity_type


def test_deep_scan_request_ignores_interactive_entity_fields():
    request = DeepScanRequest.model_validate(
        {
            "text": "MEZHDU: ACME",
            "entities": [
                {
                    "id": "det-regex-0-4-ORG",
                    "state": "pending",
                    "text": "ACME",
                    "entity_type": "ORG",
                    "start": 8,
                    "end": 12,
                    "score": 0.93,
                    "source_layer": "regex",
                    "metadata": {"placeholder": "[ORG_1]"},
                }
            ],
        }
    )

    assert len(request.entities) == 1
    assert request.entities[0].text == "ACME"
    assert request.entities[0].metadata["placeholder"] == "[ORG_1]"


def test_llm_entity_type_normalizer_drops_alternative_lists():
    assert _normalize_entity_type("ORG|PER|POSITION") is None
    assert _normalize_entity_type("ORG/PER/POSITION") is None


def test_llm_entity_type_normalizer_maps_contract_number_alias():
    assert _normalize_entity_type("CONTRACT_NUMBER") == "RU_CONTRACT_NUMBER"


def test_deanonymize_request_manual_resolutions_are_models():
    request = DeanonymizeRequest.model_validate(
        {
            "manual_resolutions": [
                {"placeholder": "[\u041e\u0422\u0421\u0423\u0422_1]", "value": "12"}
            ]
        }
    )

    assert request.manual_resolutions[0].placeholder == "[\u041e\u0422\u0421\u0423\u0422_1]"
    assert request.manual_resolutions[0].model_dump() == {
        "placeholder": "[\u041e\u0422\u0421\u0423\u0422_1]",
        "value": "12",
    }
