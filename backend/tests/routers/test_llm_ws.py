"""Tests for WebSocket LLM streaming endpoint."""

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
    resp = client.post("/api/sessions", json={"locale": "ru", "enable_llm_layer": False})
    return resp.json()["session_id"]


class TestWebSocketHandshake:
    def test_invalid_request(self):
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json({"invalid": "data"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Invalid request" in msg["content"]

    def test_session_not_found(self):
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json({
                "session_id": "nonexistent",
                "anonymized_text": "test",
                "prompt": "analyze",
                "provider": "claude",
                "model": "claude-sonnet-4-6",
            })
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Session not found" in msg["content"]

    def test_unsupported_provider(self):
        sid = _create_session()
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_json({
                "session_id": sid,
                "anonymized_text": "test",
                "prompt": "analyze",
                "provider": "gemini",
                "model": "gemini-pro",
            })
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Unsupported" in msg["content"]
