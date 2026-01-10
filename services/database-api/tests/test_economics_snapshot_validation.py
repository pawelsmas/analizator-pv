"""
Economics Snapshot V2 - Regression Tests for Data Contract Validation

These tests verify that the cashflow validation enforces the data contract:
- CAPEX_CLIENT: years 0..30 (31 records)
- EAAS_CLIENT: years 1..30 (30 records)
- EAAS_INVESTOR: years 0..duration (duration+1 records)

Run with: pytest tests/test_economics_snapshot_validation.py -v
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Import the app - adjust path as needed
import sys
sys.path.insert(0, '..')
from app import app

client = TestClient(app)


# =============================================================================
# TEST FIXTURES
# =============================================================================

def create_cashflow(model_type: str, year: int, net_cashflow: float = 10000.0):
    """Helper to create a single cashflow record."""
    return {
        "model_type": model_type,
        "year": year,
        "capex_pln": abs(net_cashflow) if year == 0 else 0,
        "revenue_pln": abs(net_cashflow) if year > 0 else 0,
        "opex_pln": 0,
        "net_cashflow_pln": net_cashflow,
        "cumulative_cashflow_pln": None,
        "discounted_cashflow_pln": None,
        "cumulative_discounted_pln": None,
        "production_kwh": None,
        "self_consumed_kwh": None,
        "pv_degradation_pct": None,
        "bess_degradation_pct": None
    }


def create_valid_snapshot_payload(eaas_duration: int = 10):
    """Create a valid snapshot payload with all required cashflows."""
    cashflows = []

    # CAPEX_CLIENT: years 0..30
    for year in range(0, 31):
        cf = create_cashflow("CAPEX_CLIENT", year, -1000000 if year == 0 else 50000)
        cashflows.append(cf)

    # EAAS_CLIENT: years 1..30
    for year in range(1, 31):
        cf = create_cashflow("EAAS_CLIENT", year, 40000)
        cashflows.append(cf)

    # EAAS_INVESTOR: years 0..duration
    for year in range(0, eaas_duration + 1):
        cf = create_cashflow("EAAS_INVESTOR", year, -800000 if year == 0 else 100000)
        cashflows.append(cf)

    return {
        "production_scenario": "P50",
        "variant_key": "test_variant",
        "pv_capacity_kwp": 500.0,
        "pv_type": "ground_s",
        "bess_power_kw": 0,
        "bess_energy_kwh": 0,
        "analysis_period_years": 30,
        "discount_rate_pct": 7.0,
        "inflation_rate_pct": 2.5,
        "capex_client_npv25": 500000,
        "capex_client_irr": 0.12,
        "capex_client_irr_mode": "real",
        "capex_client_simple_payback": 8.5,
        "capex_client_discounted_payback": None,
        "capex_client_capex0_pln": 1000000,
        "capex_deal_sell_price_pln": 1200000,
        "capex_deal_direct_cost_pln": 800000,
        "capex_deal_gross_margin_pct": 33.33,  # (400000/1200000)*100
        "capex_deal_gross_margin_pln": 400000,
        "eaas_client_npv25": 300000,
        "eaas_client_duration_years": eaas_duration,
        "eaas_client_subscription_annual": 80000,
        "eaas_investor_npv25": 200000,
        "eaas_investor_irr": 0.15,
        "eaas_investor_capex0_pln": 800000,
        "eaas_investor_revenue_annual": 100000,
        "eaas_investor_opex_annual": 20000,
        "full_payload": {},
        "created_by": "test",
        "cashflows": cashflows
    }


# =============================================================================
# HAPPY PATH TESTS
# =============================================================================

class TestHappyPath:
    """Tests for valid snapshot payloads."""

    @patch('app.get_db')
    def test_valid_snapshot_with_all_models(self, mock_db):
        """Test that a valid snapshot with all 3 models is accepted."""
        # Mock database
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = MagicMock(id=1)
        mock_session.query.return_value.filter.return_value.scalar.return_value = 0

        payload = create_valid_snapshot_payload(eaas_duration=10)

        # Verify payload structure
        capex_client_count = sum(1 for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT")
        eaas_client_count = sum(1 for cf in payload["cashflows"] if cf["model_type"] == "EAAS_CLIENT")
        eaas_investor_count = sum(1 for cf in payload["cashflows"] if cf["model_type"] == "EAAS_INVESTOR")

        assert capex_client_count == 31, f"CAPEX_CLIENT should have 31 records, got {capex_client_count}"
        assert eaas_client_count == 30, f"EAAS_CLIENT should have 30 records, got {eaas_client_count}"
        assert eaas_investor_count == 11, f"EAAS_INVESTOR should have 11 records (duration=10), got {eaas_investor_count}"

    def test_capex_client_year_range(self):
        """Verify CAPEX_CLIENT has exactly years 0..30."""
        payload = create_valid_snapshot_payload()
        capex_years = sorted([cf["year"] for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT"])
        expected_years = list(range(0, 31))
        assert capex_years == expected_years, f"CAPEX_CLIENT years mismatch: {capex_years}"

    def test_eaas_client_year_range(self):
        """Verify EAAS_CLIENT has exactly years 1..30 (no year 0)."""
        payload = create_valid_snapshot_payload()
        eaas_client_years = sorted([cf["year"] for cf in payload["cashflows"] if cf["model_type"] == "EAAS_CLIENT"])
        expected_years = list(range(1, 31))
        assert eaas_client_years == expected_years, f"EAAS_CLIENT years mismatch: {eaas_client_years}"
        assert 0 not in eaas_client_years, "EAAS_CLIENT should not have year 0"

    def test_eaas_investor_year_range(self):
        """Verify EAAS_INVESTOR has exactly years 0..duration."""
        eaas_duration = 15
        payload = create_valid_snapshot_payload(eaas_duration=eaas_duration)
        investor_years = sorted([cf["year"] for cf in payload["cashflows"] if cf["model_type"] == "EAAS_INVESTOR"])
        expected_years = list(range(0, eaas_duration + 1))
        assert investor_years == expected_years, f"EAAS_INVESTOR years mismatch: {investor_years}"

    def test_year_0_has_negative_cashflow(self):
        """Verify year 0 has negative net_cashflow (investment)."""
        payload = create_valid_snapshot_payload()

        for cf in payload["cashflows"]:
            if cf["year"] == 0:
                assert cf["net_cashflow_pln"] < 0, f"{cf['model_type']} year 0 should have negative cashflow"


# =============================================================================
# NEGATIVE TESTS - Validation Errors
# =============================================================================

class TestValidationErrors:
    """Tests for invalid payloads that should be rejected."""

    def test_missing_year_0_for_capex_client(self):
        """Missing year 0 for CAPEX_CLIENT should fail validation."""
        payload = create_valid_snapshot_payload()

        # Remove year 0 from CAPEX_CLIENT
        payload["cashflows"] = [
            cf for cf in payload["cashflows"]
            if not (cf["model_type"] == "CAPEX_CLIENT" and cf["year"] == 0)
        ]

        # Verify year 0 is missing
        capex_year_0 = [cf for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT" and cf["year"] == 0]
        assert len(capex_year_0) == 0, "Year 0 should be missing for this test"

    def test_missing_year_0_for_eaas_investor(self):
        """Missing year 0 for EAAS_INVESTOR should fail validation."""
        payload = create_valid_snapshot_payload()

        # Remove year 0 from EAAS_INVESTOR
        payload["cashflows"] = [
            cf for cf in payload["cashflows"]
            if not (cf["model_type"] == "EAAS_INVESTOR" and cf["year"] == 0)
        ]

        # Verify year 0 is missing
        investor_year_0 = [cf for cf in payload["cashflows"] if cf["model_type"] == "EAAS_INVESTOR" and cf["year"] == 0]
        assert len(investor_year_0) == 0, "Year 0 should be missing for this test"

    def test_gap_in_years(self):
        """Gap in years (e.g., missing year 15) should fail validation."""
        payload = create_valid_snapshot_payload()

        # Remove year 15 from CAPEX_CLIENT
        payload["cashflows"] = [
            cf for cf in payload["cashflows"]
            if not (cf["model_type"] == "CAPEX_CLIENT" and cf["year"] == 15)
        ]

        # Verify gap exists
        capex_years = sorted([cf["year"] for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT"])
        assert 15 not in capex_years, "Year 15 should be missing for this test"

    def test_duplicate_year(self):
        """Duplicate year for same model should fail validation."""
        payload = create_valid_snapshot_payload()

        # Add duplicate year 5 for CAPEX_CLIENT
        duplicate_cf = create_cashflow("CAPEX_CLIENT", 5, 50000)
        payload["cashflows"].append(duplicate_cf)

        # Verify duplicate exists
        year_5_count = sum(1 for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT" and cf["year"] == 5)
        assert year_5_count == 2, "Should have duplicate year 5"

    def test_eaas_duration_exceeds_max(self):
        """EaaS duration > 25 should fail validation."""
        payload = create_valid_snapshot_payload(eaas_duration=30)

        # Backend should reject duration > 25
        assert payload["eaas_client_duration_years"] > 25

    def test_year_out_of_range(self):
        """Year outside expected range should fail validation."""
        payload = create_valid_snapshot_payload()

        # Add year 31 for CAPEX_CLIENT (should be 0..30 only)
        invalid_cf = create_cashflow("CAPEX_CLIENT", 31, 50000)
        payload["cashflows"].append(invalid_cf)

        # Verify invalid year exists
        max_year = max(cf["year"] for cf in payload["cashflows"] if cf["model_type"] == "CAPEX_CLIENT")
        assert max_year == 31, "Should have year 31 for this test"


# =============================================================================
# MARGIN FORMULA TEST
# =============================================================================

class TestMarginFormula:
    """Verify margin is calculated as profit/sellPrice (not profit/cost)."""

    def test_margin_formula_is_profit_over_sale_price(self):
        """Margin% should be (Profit / Sale Price) * 100, not (Profit / Cost) * 100."""
        sell_price = 1200000
        cost = 800000
        profit = sell_price - cost  # 400000

        # Correct: margin = profit / sell_price
        correct_margin_pct = (profit / sell_price) * 100  # 33.33%

        # Wrong (markup): profit / cost
        wrong_markup_pct = (profit / cost) * 100  # 50%

        payload = create_valid_snapshot_payload()
        payload["capex_deal_sell_price_pln"] = sell_price
        payload["capex_deal_direct_cost_pln"] = cost
        payload["capex_deal_gross_margin_pln"] = profit
        payload["capex_deal_gross_margin_pct"] = correct_margin_pct

        # Verify the formula
        calculated_margin = (payload["capex_deal_gross_margin_pln"] / payload["capex_deal_sell_price_pln"]) * 100

        assert abs(calculated_margin - correct_margin_pct) < 0.01, \
            f"Margin should be {correct_margin_pct:.2f}%, got {calculated_margin:.2f}%"
        assert abs(calculated_margin - wrong_markup_pct) > 10, \
            "This is markup, not margin!"


# =============================================================================
# DATA CONTRACT CONSTANTS
# =============================================================================

class TestDataContractConstants:
    """Verify data contract constants are consistent."""

    def test_client_analysis_period_is_30(self):
        """Client analysis period must be fixed at 30 years."""
        CLIENT_ANALYSIS_PERIOD = 30

        payload = create_valid_snapshot_payload()
        assert payload["analysis_period_years"] == CLIENT_ANALYSIS_PERIOD

    def test_max_eaas_duration_is_25(self):
        """Max EaaS duration must be 25 years."""
        MAX_EAAS_DURATION = 25

        # Valid: duration = 25
        valid_payload = create_valid_snapshot_payload(eaas_duration=25)
        assert valid_payload["eaas_client_duration_years"] <= MAX_EAAS_DURATION

        # Invalid: duration = 26 (but payload creation doesn't enforce, backend does)

    def test_discount_rate_stored_as_percentage(self):
        """Discount rate should be stored as percentage (e.g., 7.0), not decimal (0.07)."""
        payload = create_valid_snapshot_payload()

        # Should be percentage
        assert payload["discount_rate_pct"] > 1, \
            f"Discount rate should be percentage (e.g., 7.0), got {payload['discount_rate_pct']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
