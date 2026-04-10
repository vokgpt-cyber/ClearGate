"""Tests for session management API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_manager import SessionManager


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Reset singleton session manager between tests."""
    SessionManager.reset()
    yield
    SessionManager.reset()


client = TestClient(app)


class TestCreateSession:
    def test_create_returns_201(self):
        resp = client.post("/api/sessions", json={"locale": "ru"})
        assert resp.status_code == 201

    def test_create_returns_session_id(self):
        resp = client.post("/api/sessions", json={})
        data = resp.json()
        assert "session_id" in data
        assert "created_at" in data
        assert "expires_at" in data

    def test_default_locale_ru(self):
        resp = client.post("/api/sessions", json={})
        assert resp.status_code == 201


class TestGetSession:
    def test_get_existing(self):
        create_resp = client.post("/api/sessions", json={})
        sid = create_resp.json()["session_id"]
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid

    def test_get_nonexistent_returns_404(self):
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404


class TestCloseSession:
    def test_close_existing(self):
        create_resp = client.post("/api/sessions", json={})
        sid = create_resp.json()["session_id"]
        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 204

    def test_close_then_get_returns_404(self):
        create_resp = client.post("/api/sessions", json={})
        sid = create_resp.json()["session_id"]
        client.delete(f"/api/sessions/{sid}")
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 404
