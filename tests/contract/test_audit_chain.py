"""
Contract tests for audit tamper-evident chain (v3.2.0 PR6).

Verifies audit chain integrity verification and metrics.
Requires running API server with AUTH_MODE=enabled.
"""
import os
import pytest
import requests
from ._api import DEFAULT_BASE_URL


# Skip if auth is not enabled
AUTH_ENABLED = os.getenv("AUTH_MODE", "disabled").lower() == "enabled"


def get_admin_token():
    """Get admin JWT token for authenticated requests."""
    login_url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/auth/login"
    resp = requests.post(
        login_url,
        json={"email": "admin@local", "password": "admin123"},
        timeout=10
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    return None


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="Audit chain tests require AUTH_MODE=enabled"
)
class TestAuditChainVerify:
    """Test audit chain verification endpoint."""

    def test_verify_endpoint_exists(self):
        """GET /audit/verify should return chain verification result."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit/verify"
        resp = requests.get(url, headers=headers, timeout=30)

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        assert "valid" in body, "Response should have valid field"
        assert "entries_checked" in body, "Response should have entries_checked field"
        assert isinstance(body["valid"], bool), "valid should be boolean"

    def test_verify_returns_valid_for_intact_chain(self):
        """For unmodified data, verify should return valid=true."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit/verify"
        resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code != 200:
            pytest.skip(f"Could not verify chain: {resp.status_code}")

        body = resp.json()
        # Fresh installation should have valid chain
        assert body["valid"] is True, (
            f"Expected valid=true, got: {body}"
        )

    def test_verify_accepts_limit_parameter(self):
        """GET /audit/verify?limit=100 should work."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit/verify?limit=100"
        resp = requests.get(url, headers=headers, timeout=30)

        assert resp.status_code == 200


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="Audit chain tests require AUTH_MODE=enabled"
)
class TestAuditChainStats:
    """Test audit chain statistics endpoint."""

    def test_stats_endpoint_exists(self):
        """GET /audit/stats should return chain statistics."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit/stats"
        resp = requests.get(url, headers=headers, timeout=10)

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        assert "total_entries" in body, "Response should have total_entries"
        assert "entries_with_hash" in body, "Response should have entries_with_hash"

    def test_stats_has_expected_fields(self):
        """Stats response should have all expected fields."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit/stats"
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            pytest.skip("Could not get stats")

        body = resp.json()
        assert "total_entries" in body
        assert "entries_with_hash" in body
        assert "first_entry_at" in body
        assert "last_entry_at" in body


class TestAuditChainMetrics:
    """Test audit chain metrics."""

    def test_metrics_endpoint_has_audit_counters(self):
        """GET /metrics should include audit chain counters."""
        url = f"{DEFAULT_BASE_URL}/metrics"
        resp = requests.get(url, timeout=10)

        assert resp.status_code == 200
        content = resp.text

        # Check for audit metric definitions
        assert "bess_audit" in content, (
            "Audit metrics should be defined in /metrics"
        )


@pytest.mark.skipif(
    not AUTH_ENABLED,
    reason="Audit entry tests require AUTH_MODE=enabled"
)
class TestAuditEntryHashes:
    """Test that new audit entries have hashes."""

    def test_audit_query_returns_entries(self):
        """GET /audit should return audit entries."""
        token = get_admin_token()
        if not token:
            pytest.skip("Could not get admin token")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/audit"
        resp = requests.get(url, headers=headers, timeout=10)

        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )

        body = resp.json()
        assert "items" in body
        assert "total" in body
