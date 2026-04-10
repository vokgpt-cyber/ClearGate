"""Tests for document upload and parsing endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestParseText:
    def test_parse_text(self):
        resp = client.post(
            "/api/documents/parse-text",
            json={"text": "Простой текст для анализа"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "txt"
        assert data["char_count"] > 0

    def test_parse_text_empty_rejected(self):
        resp = client.post("/api/documents/parse-text", json={"text": ""})
        assert resp.status_code == 422


class TestUploadDocument:
    def test_upload_txt(self):
        content = "Тестовый документ с ИНН 7707083893".encode("utf-8")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", content, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "txt"
        assert "7707083893" in data["text"]

    def test_upload_unsupported_format(self):
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.exe", b"binary", "application/octet-stream")},
        )
        assert resp.status_code == 415
