"""Tests for anonymize API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_manager import SessionManager


@pytest.fixture(autouse=True)
def _reset_sessions():
    SessionManager.reset()
    yield
    SessionManager.reset()


client = TestClient(app)


def _create_session():
    """Helper: create a session and return its ID."""
    resp = client.post("/api/sessions", json={"locale": "ru", "enable_llm_layer": False})
    return resp.json()["session_id"]


class TestAnonymize:
    def test_anonymize_text_with_inn(self):
        sid = _create_session()
        resp = client.post(
            f"/api/sessions/{sid}/anonymize",
            json={"text": "ИНН организации: 7707083893"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "anonymized_text" in data
        assert "entities" in data
        assert "stats" in data
        # INN should be detected and replaced
        assert "7707083893" not in data["anonymized_text"]

    def test_anonymize_nonexistent_session(self):
        resp = client.post(
            "/api/sessions/nonexistent/anonymize",
            json={"text": "test"},
        )
        assert resp.status_code == 404

    def test_anonymize_empty_text_rejected(self):
        sid = _create_session()
        resp = client.post(f"/api/sessions/{sid}/anonymize", json={"text": ""})
        assert resp.status_code == 422  # validation error


class TestDeanonymize:
    def test_deanonymize(self):
        sid = _create_session()
        # First anonymize
        client.post(
            f"/api/sessions/{sid}/anonymize",
            json={"text": "ИНН организации: 7707083893"},
        )
        # Then deanonymize
        resp = client.post(
            f"/api/sessions/{sid}/deanonymize",
            json={"text": "[ИНН_1] — это наш номер"},
        )
        assert resp.status_code == 200
        # Placeholder should be replaced
        assert "[ИНН_1]" not in resp.json()["text"]


class TestGetEntities:
    def test_get_entities_after_anonymize(self):
        sid = _create_session()
        client.post(
            f"/api/sessions/{sid}/anonymize",
            json={"text": "ИНН организации: 7707083893"},
        )
        resp = client.get(f"/api/sessions/{sid}/entities")
        assert resp.status_code == 200
        assert "entities" in resp.json()
        assert len(resp.json()["entities"]) >= 1

    def test_get_entities_empty_session(self):
        sid = _create_session()
        resp = client.get(f"/api/sessions/{sid}/entities")
        assert resp.status_code == 200
        assert resp.json()["entities"] == []
