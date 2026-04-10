"""Tests for health check endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self):
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "profile" in data
        assert "timestamp" in data

    def test_health_status_ok(self):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_version_matches_config(self):
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "0.1.0-alpha"

    def test_health_profile_default(self):
        response = client.get("/health")
        data = response.json()
        assert data["profile"] == "alpha"


class TestReadinessEndpoint:
    """Tests for GET /health/ready."""

    def test_readiness_returns_200(self):
        response = client.get("/health/ready")
        assert response.status_code == 200

    def test_readiness_not_ready_initially(self):
        response = client.get("/health/ready")
        data = response.json()
        assert data["ready"] is False

    def test_readiness_has_checks(self):
        response = client.get("/health/ready")
        data = response.json()
        assert "checks" in data
        assert "models_loaded" in data["checks"]
        assert "ollama_available" in data["checks"]
