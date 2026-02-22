"""
Smoke Tests E2E: Customer Portal Integration

These tests verify the complete flow:
1. Project with snapshot -> offer-package (CUSTOMER_SAFE)
2. Publish -> creates v1 in history
3. Republish -> creates v2
4. Credit attach -> saves reference only
5. Negative tests

Run with: pytest tests/test_smoke_e2e_integration.py -v

Note: These tests use mocked database via FastAPI dependency overrides.
For full integration tests, use the SQL verification queries in
sql_verification_checklist.sql
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from decimal import Decimal
import sys
sys.path.insert(0, '..')

from app import app, BANNED_FIELDS_CUSTOMER_SAFE, get_db

client = TestClient(app)


def override_get_db(mock_session):
    """Create a dependency override for get_db."""
    def _override():
        return mock_session
    return _override


# =============================================================================
# MOCK FIXTURES
# =============================================================================

def create_mock_project(id=1, name="Test Solar Farm", offer_id=None, offer_version=None, published=False):
    """Create a mock Project object.

    Args:
        published: If True, sets offer_published_at to current time (required for customer access)
    """
    project = MagicMock()
    project.id = id
    project.name = name
    project.company_id = 1
    project.location_name = "Warsaw"
    project.offer_id = offer_id
    project.offer_version = offer_version
    project.offer_published_at = datetime.now() if published else None
    project.selected_snapshot_id = None
    project.selected_option_key = None
    project.hubspot_company_id = None
    project.hubspot_deal_id = None
    project.portfolio_company_id = None
    return project


def create_mock_snapshot(id=1, project_id=1, variant_key="A"):
    """Create a mock ProjectEconomicsSnapshot object."""
    snapshot = MagicMock()
    snapshot.id = id
    snapshot.project_id = project_id
    snapshot.variant_key = variant_key
    snapshot.production_scenario = "P50"
    snapshot.pv_capacity_kwp = Decimal("500.0")
    snapshot.pv_type = "ground_s"
    snapshot.bess_power_kw = Decimal("0")
    snapshot.bess_energy_kwh = Decimal("0")
    snapshot.capex_client_npv = Decimal("500000")
    snapshot.capex_client_irr = Decimal("0.125")
    snapshot.capex_client_simple_payback = Decimal("8.5")
    snapshot.capex_client_capex0_pln = Decimal("1400000")
    snapshot.capex_deal_sell_price_pln = Decimal("1707300")
    snapshot.capex_deal_direct_cost_pln = Decimal("1400000")  # INTERNAL - should not leak
    snapshot.capex_deal_gross_margin_pln = Decimal("307300")  # INTERNAL - should not leak
    snapshot.capex_deal_gross_margin_pct = Decimal("18.0")  # INTERNAL - should not leak
    snapshot.eaas_client_npv = Decimal("300000")
    snapshot.eaas_client_duration_years = 15
    snapshot.eaas_client_subscription_annual = Decimal("96000")
    snapshot.eaas_client_subscription_monthly = Decimal("8000")
    snapshot.eaas_client_price_per_mwh = Decimal("350")
    snapshot.eaas_investor_npv = Decimal("200000")  # INTERNAL - should not leak
    snapshot.eaas_investor_project_irr = Decimal("0.15")  # INTERNAL - should not leak
    snapshot.full_payload = {"internal": "data"}  # INTERNAL - should not leak
    snapshot.created_at = datetime.now()
    snapshot.credit_risk_class = None
    snapshot.max_eaas_duration_allowed = None
    snapshot.is_customer_visible = False
    snapshot.customer_portal_published_at = None
    snapshot.cashflows = []
    return snapshot


def create_mock_company(id=1, name="Test Company"):
    """Create a mock Company object."""
    company = MagicMock()
    company.id = id
    company.name = name
    company.credit_risk_class = "B"
    company.credit_limit_pln = Decimal("5000000")
    company.max_eaas_duration_years = 20
    company.approval_required = False
    company.required_deposit_pct = None
    company.required_security = None
    company.credit_score_updated_at = datetime.now()
    return company


# =============================================================================
# SMOKE TEST 1: Offer Package is CUSTOMER_SAFE
# =============================================================================

class TestOfferPackageCustomerSafe:
    """Test that offer-package returns only CUSTOMER_SAFE data."""

    def test_offer_package_contains_no_internal_fields(self):
        """Offer package must not contain any banned internal fields."""
        # Setup mocks
        mock_session = MagicMock()

        # Use published=True to allow customer access
        project = create_mock_project(published=True)
        snapshot = create_mock_snapshot()
        company = create_mock_company()

        # Configure query returns
        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                q.filter.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.all.return_value = [snapshot]
            elif 'Company' in str(model):
                q.filter.return_value.first.return_value = company
            elif 'EnergyProfile' in str(model):
                q.filter.return_value.first.return_value = None
            return q

        mock_session.query.side_effect = mock_query

        # Use FastAPI dependency override
        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.get("/projects/1/offer-package")
            assert response.status_code == 200

            data = response.json()

            # Check that NO banned fields appear anywhere in response
            def check_no_banned_fields(obj, path=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current = f"{path}.{key}" if path else key
                        # Check key is not banned
                        assert key.lower() not in {f.lower() for f in BANNED_FIELDS_CUSTOMER_SAFE}, \
                            f"BANNED FIELD LEAKED: {current}"
                        check_no_banned_fields(value, current)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        check_no_banned_fields(item, f"{path}[{i}]")

            check_no_banned_fields(data)
            print("PASS: Offer package contains no internal fields")
        finally:
            app.dependency_overrides.clear()

    def test_offer_package_shows_sell_price_not_cost(self):
        """Customer sees sell_price (investment), NOT cost."""
        mock_session = MagicMock()

        # Use published=True to allow customer access
        project = create_mock_project(published=True)
        snapshot = create_mock_snapshot()
        company = create_mock_company()

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                q.filter.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.all.return_value = [snapshot]
            elif 'Company' in str(model):
                q.filter.return_value.first.return_value = company
            elif 'EnergyProfile' in str(model):
                q.filter.return_value.first.return_value = None
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.get("/projects/1/offer-package")
            assert response.status_code == 200

            data = response.json()

            # Check capex_economics.investment_pln is sell_price (1707300), not cost (1400000)
            investment = data["capex_economics"]["investment_pln"]
            assert investment == 1707300, f"Expected sell_price 1707300, got {investment}"
            print(f"PASS: Customer sees investment_pln={investment} (sell price, not cost)")
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# SMOKE TEST 2: Publish Creates Audit Trail
# =============================================================================

class TestPublishAuditTrail:
    """Test that publish creates immutable audit records."""

    def test_publish_creates_v1(self):
        """First publish creates v1 in history."""
        mock_session = MagicMock()

        project = create_mock_project()
        snapshot = create_mock_snapshot()

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                # Handle chained filter().filter().first()
                q.filter.return_value.filter.return_value.first.return_value = snapshot
                q.filter.return_value.first.return_value = snapshot
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.post(
                "/projects/1/publish-to-customer-portal",
                json={"snapshot_id": 1, "option_key": "A"},
                headers={"Authorization": "Bearer admin_xyz123"}
            )
            assert response.status_code == 200

            data = response.json()
            assert data["success"] == True
            assert data["offer_version"] == "v1"
            assert "offer_id" in data
            print(f"PASS: First publish created offer_id={data['offer_id']} version={data['offer_version']}")
        finally:
            app.dependency_overrides.clear()

    def test_republish_increments_version(self):
        """Republish increments version to v2."""
        mock_session = MagicMock()

        # Project already has v1 published - use published=True
        project = create_mock_project(offer_id="OFFER-2026-0001", offer_version="v1", published=True)
        snapshot = create_mock_snapshot()

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                # Handle chained filter().filter().first()
                q.filter.return_value.filter.return_value.first.return_value = snapshot
                q.filter.return_value.first.return_value = snapshot
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.post(
                "/projects/1/publish-to-customer-portal",
                json={"snapshot_id": 1, "option_key": "B"},
                headers={"Authorization": "Bearer admin_xyz123"}
            )
            assert response.status_code == 200

            data = response.json()
            assert data["offer_version"] == "v2", f"Expected v2, got {data['offer_version']}"
            print(f"PASS: Republish incremented to version={data['offer_version']}")
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# SMOKE TEST 3: Credit Attach Saves Reference Only
# =============================================================================

class TestCreditAttach:
    """Test that credit attach only saves reference, no policy logic."""

    def test_attach_credit_saves_reference(self):
        """Attach credit decision saves reference from Portfolio."""
        mock_session = MagicMock()

        snapshot = create_mock_snapshot()
        company = create_mock_company()

        def mock_query(model):
            q = MagicMock()
            if 'ProjectEconomicsSnapshot' in str(model):
                q.filter.return_value.first.return_value = snapshot
            elif 'Company' in str(model):
                q.filter.return_value.first.return_value = company
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.post(
                "/economics-snapshot/1/attach-credit-decision?company_id=1",
                headers={"Authorization": "Bearer admin_xyz123"}
            )
            assert response.status_code == 200

            data = response.json()
            assert data["status"] == "ok"
            assert data["credit_risk_class"] == "B"  # From company, not calculated
            assert data["source"] == "Portfolio Management"
            print(f"PASS: Credit decision attached from Portfolio: class={data['credit_risk_class']}")
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# SMOKE TEST 4: Negative Tests
# =============================================================================

class TestNegativeCases:
    """Test error cases and access denials."""

    def test_customer_token_denied_admin_endpoint(self):
        """Customer token cannot access admin endpoints."""
        response = client.put(
            "/projects/1/integration",
            json={"selected_option_key": "A"},
            headers={"Authorization": "Bearer customer_xyz123"}
        )
        assert response.status_code == 403
        print("PASS: Customer token denied on admin endpoint")

    def test_no_token_denied_internal_endpoint(self):
        """No token cannot access internal endpoints."""
        response = client.get("/projects/1/publication-history")
        assert response.status_code == 403
        print("PASS: No token denied on internal endpoint")

    def test_unpublished_project_returns_404_for_customers(self):
        """Unpublished project returns 404 for customer/anonymous access.

        Security: Customers can only see published offers.
        Internal users can access drafts with allow_draft=true.
        """
        mock_session = MagicMock()

        project = create_mock_project()  # No offer_published_at = unpublished
        snapshot = create_mock_snapshot()
        company = create_mock_company()

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                q.filter.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.first.return_value = snapshot
                q.filter.return_value.order_by.return_value.all.return_value = [snapshot]
            elif 'Company' in str(model):
                q.filter.return_value.first.return_value = company
            elif 'EnergyProfile' in str(model):
                q.filter.return_value.first.return_value = None
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            # No token (anonymous) - should get 404 for unpublished
            response = client.get("/projects/1/offer-package")
            assert response.status_code == 404
            print("PASS: Unpublished project returns 404 for anonymous users")
        finally:
            app.dependency_overrides.clear()

    def test_no_snapshot_returns_404(self):
        """Project with no snapshot returns 404."""
        mock_session = MagicMock()

        # Published project but no snapshot
        project = create_mock_project(published=True)

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'ProjectEconomicsSnapshot' in str(model):
                q.filter.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.first.return_value = None
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.get("/projects/1/offer-package")
            assert response.status_code == 404
            print("PASS: No snapshot returns 404")
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# SMOKE TEST 5: Publication History is Internal Only
# =============================================================================

class TestPublicationHistorySecurity:
    """Test that publication history is internal-only and safe."""

    def test_history_accessible_with_internal_token(self):
        """Publication history accessible with internal token."""
        mock_session = MagicMock()

        project = create_mock_project()

        def mock_query(model):
            q = MagicMock()
            if 'Project' in str(model):
                q.filter.return_value.first.return_value = project
            elif 'OfferPublicationHistory' in str(model):
                q.filter.return_value.order_by.return_value.all.return_value = []
            return q

        mock_session.query.side_effect = mock_query

        app.dependency_overrides[get_db] = override_get_db(mock_session)
        try:
            response = client.get(
                "/projects/1/publication-history",
                headers={"Authorization": "Bearer internal_xyz123"}
            )
            assert response.status_code == 200
            print("PASS: Publication history accessible with internal token")
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# SUMMARY REPORT
# =============================================================================

def run_all_smoke_tests():
    """Run all smoke tests and print summary."""
    print("\n" + "="*60)
    print("SMOKE TEST E2E: Customer Portal Integration")
    print("="*60 + "\n")

    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    run_all_smoke_tests()
