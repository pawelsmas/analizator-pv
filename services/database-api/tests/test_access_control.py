"""
Access Control Tests

These tests verify that:
1. ADMIN endpoints reject non-admin tokens
2. INTERNAL endpoints reject customer tokens
3. CUSTOMER_SAFE endpoints are accessible (with proper token when required)

Run with: pytest tests/test_access_control.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, '..')

from app import app, TokenType, get_token_type

client = TestClient(app)


# =============================================================================
# TOKEN TYPE DETECTION TESTS
# =============================================================================

class TestTokenTypeDetection:
    """Test token type extraction from Authorization header."""

    def test_no_token_returns_none_type(self):
        """No Authorization header should return NONE type."""
        result = get_token_type(None)
        assert result == TokenType.NONE

    def test_admin_token_detected(self):
        """Admin token should be detected."""
        result = get_token_type("Bearer admin_xyz123")
        assert result == TokenType.ADMIN

    def test_internal_token_detected(self):
        """Internal token should be detected."""
        result = get_token_type("Bearer internal_abc456")
        assert result == TokenType.INTERNAL

    def test_customer_token_detected(self):
        """Customer token should be detected."""
        result = get_token_type("Bearer customer_def789")
        assert result == TokenType.CUSTOMER

    def test_legacy_token_treated_as_internal(self):
        """Legacy tokens (without prefix) treated as internal for backwards compat."""
        result = get_token_type("Bearer some_legacy_token_here")
        assert result == TokenType.INTERNAL

    def test_invalid_bearer_format(self):
        """Invalid Bearer format returns NONE."""
        result = get_token_type("Basic xyz123")
        assert result == TokenType.NONE


# =============================================================================
# ADMIN ENDPOINT ACCESS TESTS
# =============================================================================

class TestAdminEndpointAccess:
    """Test that ADMIN endpoints reject non-admin tokens."""

    def test_integration_update_requires_admin(self):
        """PUT /projects/{id}/integration requires admin token."""
        # No token
        response = client.put(
            "/projects/1/integration",
            json={"selected_option_key": "A"}
        )
        assert response.status_code == 403

        # Customer token
        response = client.put(
            "/projects/1/integration",
            json={"selected_option_key": "A"},
            headers={"Authorization": "Bearer customer_xyz"}
        )
        assert response.status_code == 403

        # Internal token
        response = client.put(
            "/projects/1/integration",
            json={"selected_option_key": "A"},
            headers={"Authorization": "Bearer internal_xyz"}
        )
        assert response.status_code == 403

    def test_publish_requires_admin(self):
        """POST /projects/{id}/publish-to-customer-portal requires admin token."""
        # No token
        response = client.post(
            "/projects/1/publish-to-customer-portal",
            json={"snapshot_id": 1, "option_key": "A"}
        )
        assert response.status_code == 403

        # Customer token
        response = client.post(
            "/projects/1/publish-to-customer-portal",
            json={"snapshot_id": 1, "option_key": "A"},
            headers={"Authorization": "Bearer customer_xyz"}
        )
        assert response.status_code == 403

    def test_attach_credit_decision_requires_admin(self):
        """POST /economics-snapshot/{id}/attach-credit-decision requires admin."""
        response = client.post(
            "/economics-snapshot/1/attach-credit-decision?company_id=1"
        )
        assert response.status_code == 403

        response = client.post(
            "/economics-snapshot/1/attach-credit-decision?company_id=1",
            headers={"Authorization": "Bearer internal_xyz"}
        )
        assert response.status_code == 403


# =============================================================================
# INTERNAL ENDPOINT ACCESS TESTS
# =============================================================================

class TestInternalEndpointAccess:
    """Test that INTERNAL endpoints reject customer tokens."""

    def test_publication_history_requires_internal(self):
        """GET /projects/{id}/publication-history requires internal or admin."""
        # No token
        response = client.get("/projects/1/publication-history")
        assert response.status_code == 403

        # Customer token
        response = client.get(
            "/projects/1/publication-history",
            headers={"Authorization": "Bearer customer_xyz"}
        )
        assert response.status_code == 403

    def test_credit_decision_requires_internal(self):
        """GET /companies/{id}/credit-decision requires internal or admin."""
        # Customer token should be rejected
        response = client.get(
            "/companies/1/credit-decision",
            headers={"Authorization": "Bearer customer_xyz"}
        )
        assert response.status_code == 403


# =============================================================================
# CUSTOMER_SAFE ENDPOINT ACCESS TESTS
# =============================================================================

class TestCustomerSafeEndpointAccess:
    """Test that CUSTOMER_SAFE endpoints are accessible."""

    @patch('app.get_db')
    def test_offer_package_accessible_without_auth(self, mock_db):
        """GET /projects/{id}/offer-package should be accessible.

        Note: In production, this might require customer token.
        For now, testing that it doesn't require admin/internal.
        """
        # Mock database to return 404 (project not found is OK, we're testing auth)
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Should not get 403 (auth error)
        response = client.get("/projects/999/offer-package")
        # 404 is OK (project not found), 403 would be wrong
        assert response.status_code != 403


# =============================================================================
# ADMIN TOKEN SUCCESS TESTS
# =============================================================================

class TestAdminTokenSuccess:
    """Test that admin tokens grant access to protected endpoints."""

    @patch('app.get_db')
    def test_integration_update_with_admin_token(self, mock_db):
        """PUT /projects/{id}/integration succeeds with admin token."""
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put(
            "/projects/1/integration",
            json={"selected_option_key": "A"},
            headers={"Authorization": "Bearer admin_xyz123"}
        )
        # 404 is OK (project not found), 403 would mean auth failed
        assert response.status_code != 403

    @patch('app.get_db')
    def test_publish_with_admin_token(self, mock_db):
        """POST /projects/{id}/publish-to-customer-portal succeeds with admin."""
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.post(
            "/projects/1/publish-to-customer-portal",
            json={"snapshot_id": 1, "option_key": "A"},
            headers={"Authorization": "Bearer admin_xyz123"}
        )
        assert response.status_code != 403


# =============================================================================
# INTERNAL TOKEN SUCCESS TESTS
# =============================================================================

class TestInternalTokenSuccess:
    """Test that internal tokens grant access to internal endpoints."""

    @patch('app.get_db')
    def test_publication_history_with_internal_token(self, mock_db):
        """GET /projects/{id}/publication-history succeeds with internal token."""
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.get(
            "/projects/1/publication-history",
            headers={"Authorization": "Bearer internal_xyz123"}
        )
        assert response.status_code != 403

    @patch('app.get_db')
    def test_publication_history_with_admin_token(self, mock_db):
        """GET /projects/{id}/publication-history also succeeds with admin token."""
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.get(
            "/projects/1/publication-history",
            headers={"Authorization": "Bearer admin_xyz123"}
        )
        assert response.status_code != 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
