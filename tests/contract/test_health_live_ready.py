"""
Contract tests for Kubernetes health probe endpoints (v3.5.0).

Tests verify:
- GET /api/bess-dispatch/health/live returns 200 always
- GET /api/bess-dispatch/health/ready returns 200 when dependencies healthy
- Response structures match expected schemas
- Dependency checks are included in ready response
"""
import pytest
import requests

BASE_URL = "http://localhost:8031"


class TestHealthLiveEndpoint:
    """Contract tests for liveness probe endpoint."""

    def test_live_endpoint_returns_200(self):
        """Verify /health/live endpoint returns 200."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
        assert response.status_code == 200

    def test_live_has_status_field(self):
        """Verify response has status field set to 'ok'."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
        data = response.json()

        assert "status" in data
        assert data["status"] == "ok"

    def test_live_has_service_field(self):
        """Verify response has service field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
        data = response.json()

        assert "service" in data
        assert data["service"] == "bess-dispatch"

    def test_live_content_type_json(self):
        """Verify response content type is JSON."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")

        assert "application/json" in response.headers.get("content-type", "")

    def test_live_all_fields_present(self):
        """Verify all required fields are present."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
        data = response.json()

        required_fields = ["status", "service"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"


class TestHealthReadyEndpoint:
    """Contract tests for readiness probe endpoint."""

    def test_ready_endpoint_returns_200_when_healthy(self):
        """Verify /health/ready endpoint returns 200 when all deps healthy."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        # Should return 200 in test environment (default SQLite)
        assert response.status_code == 200

    def test_ready_has_status_field(self):
        """Verify response has status field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "status" in data
        assert data["status"] in ("ok", "degraded")

    def test_ready_has_service_field(self):
        """Verify response has service field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "service" in data
        assert data["service"] == "bess-dispatch"

    def test_ready_has_checks_field(self):
        """Verify response has checks field with dependency results."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_ready_checks_has_db_field(self):
        """Verify checks includes db check result."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "db" in data["checks"]
        db_check = data["checks"]["db"]
        assert "status" in db_check
        assert "latency_ms" in db_check

    def test_ready_checks_has_redis_field(self):
        """Verify checks includes redis check result."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "redis" in data["checks"]
        redis_check = data["checks"]["redis"]
        assert "status" in redis_check
        # Redis is disabled by default
        assert redis_check["status"] in ("ok", "disabled", "not_installed", "error")

    def test_ready_checks_has_s3_field(self):
        """Verify checks includes s3 check result."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "s3" in data["checks"]
        s3_check = data["checks"]["s3"]
        assert "status" in s3_check
        # S3 is disabled by default
        assert s3_check["status"] in ("ok", "disabled", "not_installed", "not_configured", "error")

    def test_ready_has_message_field(self):
        """Verify response has message field."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        assert "message" in data
        # Message should describe health status
        assert isinstance(data["message"], (str, type(None)))

    def test_ready_content_type_json(self):
        """Verify response content type is JSON."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")

        assert "application/json" in response.headers.get("content-type", "")

    def test_ready_all_fields_present(self):
        """Verify all required fields are present."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        required_fields = ["status", "service", "checks", "message"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_ready_db_check_structure(self):
        """Verify db check has complete structure."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        db_check = data["checks"]["db"]

        # Required fields
        assert "status" in db_check
        assert "latency_ms" in db_check
        assert isinstance(db_check["latency_ms"], (int, float))

        # DB should be ok or not_initialized in test environment
        assert db_check["status"] in ("ok", "disabled", "not_initialized", "error")

    def test_ready_status_ok_when_db_healthy(self):
        """Verify ready status is 'ok' when db check passes."""
        response = requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
        data = response.json()

        db_check = data["checks"]["db"]

        # If DB is ok or disabled, overall status should be ok
        if db_check["status"] in ("ok", "disabled", "not_initialized"):
            assert data["status"] == "ok"


class TestHealthEndpointIdempotency:
    """Test that health endpoints are idempotent."""

    def test_live_idempotent(self):
        """Verify multiple live requests return same result."""
        responses = [
            requests.get(f"{BASE_URL}/api/bess-dispatch/health/live")
            for _ in range(3)
        ]

        # All should return 200
        for r in responses:
            assert r.status_code == 200

        # All should have same status
        statuses = [r.json()["status"] for r in responses]
        assert all(s == "ok" for s in statuses)

    def test_ready_idempotent(self):
        """Verify multiple ready requests return consistent result."""
        responses = [
            requests.get(f"{BASE_URL}/api/bess-dispatch/health/ready")
            for _ in range(3)
        ]

        # All should return same status code
        codes = [r.status_code for r in responses]
        assert len(set(codes)) == 1

        # All should have same status
        statuses = [r.json()["status"] for r in responses]
        assert len(set(statuses)) == 1
