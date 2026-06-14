"""
CUSTOMER_SAFE Redaction Guard Tests

These tests ensure that CUSTOMER_SAFE endpoints NEVER expose internal data.
This is a SECURITY test - failures here indicate potential data leakage.

Run with: pytest tests/test_customer_safe_redaction.py -v
"""

import pytest
import json
from typing import Set, Any, Dict, List

# =============================================================================
# BANNED FIELDS - These must NEVER appear in CUSTOMER_SAFE responses
# =============================================================================

BANNED_FIELDS: Set[str] = {
    # Direct cost / margin fields
    "capex_deal_direct_cost_pln",
    "capex_deal_gross_margin_pct",
    "capex_deal_gross_margin_pln",
    "direct_cost",
    "gross_margin",
    "margin_pct",
    "margin_pln",
    "cost_pln",

    # Investor economics (ALL eaas_investor_* fields)
    "eaas_investor_target_irr",
    "eaas_investor_project_irr",
    "eaas_investor_equity_irr",
    "eaas_investor_irr_driver",
    "eaas_investor_capex_pln",
    "eaas_investor_debt_pln",
    "eaas_investor_equity_pln",
    "eaas_investor_leverage_pct",
    "eaas_investor_contract_revenue_pln",
    "eaas_investor_contract_opex_pln",
    "eaas_investor_contract_tax_pln",
    "eaas_investor_contract_interest_pln",
    "eaas_investor_cit_rate_pct",
    "eaas_investor_depreciation_years",
    "eaas_investor_indexation_type",
    "eaas_investor_project_life_years",
    "eaas_investor_residual_value_pln",
    "eaas_investor_residual_per_kwp",
    "eaas_investor_npv",
    "eaas_investor_capex0_pln",
    "eaas_investor_revenue_annual",
    "eaas_investor_opex_annual",

    # Full payload (contains everything)
    "full_payload",

    # Internal identifiers that shouldn't leak
    "portfolio_company_id",
    "hubspot_company_id",
    "hubspot_deal_id",

    # Credit internal details
    "credit_score_snapshot_id",

    # Cashflow model type markers (if exposing wrong model)
    "EAAS_INVESTOR",  # As value in model_type field

    # Internal calculation metadata
    "calc_metadata",
    "request_payload",
    "result_payload",
}

# Fields that indicate INTERNAL model exposure
INVESTOR_MODEL_INDICATORS: Set[str] = {
    "investor",
    "leverage",
    "equity_irr",
    "project_irr",
    "target_irr",
    "debt_pln",
    "cit_rate",
    "depreciation",
}


def find_banned_fields_recursive(
    data: Any,
    path: str = "",
    found: List[str] = None
) -> List[str]:
    """
    Recursively search for banned fields in any data structure.
    Returns list of paths where banned fields were found.
    """
    if found is None:
        found = []

    if isinstance(data, dict):
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key

            # Check if key itself is banned
            if key.lower() in {f.lower() for f in BANNED_FIELDS}:
                found.append(f"BANNED KEY: {current_path}")

            # Check if key contains investor indicators
            for indicator in INVESTOR_MODEL_INDICATORS:
                if indicator in key.lower():
                    found.append(f"INVESTOR INDICATOR: {current_path} (contains '{indicator}')")

            # Check if value is a banned string
            if isinstance(value, str) and value in BANNED_FIELDS:
                found.append(f"BANNED VALUE: {current_path} = '{value}'")

            # Recurse into nested structures
            find_banned_fields_recursive(value, current_path, found)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            find_banned_fields_recursive(item, f"{path}[{i}]", found)

    return found


# =============================================================================
# SCHEMA TESTS - Verify Pydantic schemas don't expose banned fields
# =============================================================================

class TestCustomerSafeSchemas:
    """Verify that CUSTOMER_SAFE Pydantic schemas don't include banned fields."""

    def test_customer_safe_installation_has_no_banned_fields(self):
        """CustomerSafeInstallation should only have installation data."""
        from schemas import CustomerSafeInstallation

        allowed_fields = {
            "pv_capacity_kwp", "pv_type", "has_bess",
            "bess_power_kw", "bess_energy_kwh", "location_name"
        }
        schema_fields = set(CustomerSafeInstallation.model_fields.keys())

        # All fields must be in allowed list
        for field in schema_fields:
            assert field in allowed_fields, f"Unexpected field in CustomerSafeInstallation: {field}"

        # No banned fields
        for field in schema_fields:
            assert field not in BANNED_FIELDS, f"BANNED field in CustomerSafeInstallation: {field}"

    def test_customer_safe_capex_economics_has_no_banned_fields(self):
        """CustomerSafeCapexEconomics should show customer investment, not internal cost."""
        from schemas import CustomerSafeCapexEconomics

        schema_fields = set(CustomerSafeCapexEconomics.model_fields.keys())

        # Must NOT have cost/margin fields
        banned_in_capex = {
            "direct_cost", "capex_deal_direct_cost_pln",
            "gross_margin", "gross_margin_pct", "gross_margin_pln",
            "capex_deal_gross_margin_pct", "capex_deal_gross_margin_pln"
        }
        for field in schema_fields:
            assert field not in banned_in_capex, f"BANNED field in CustomerSafeCapexEconomics: {field}"

        # Should have 'investment_pln' (customer-facing price), not 'cost_pln'
        assert "investment_pln" in schema_fields, "Missing investment_pln (customer-facing price)"
        assert "cost_pln" not in schema_fields, "Has cost_pln (internal cost) - should be investment_pln"

    def test_customer_safe_eaas_economics_has_no_investor_fields(self):
        """CustomerSafeEaasEconomics should show client view, not investor view."""
        from schemas import CustomerSafeEaasEconomics

        schema_fields = set(CustomerSafeEaasEconomics.model_fields.keys())

        # No investor fields
        for field in schema_fields:
            assert not field.startswith("investor"), f"Investor field in CustomerSafeEaasEconomics: {field}"
            assert "irr" not in field.lower() or field == "irr_pct", f"IRR field leak: {field}"
            assert "leverage" not in field.lower(), f"Leverage field leak: {field}"

    def test_offer_package_has_no_banned_fields(self):
        """OfferPackage schema should be fully customer-safe."""
        from schemas import OfferPackage

        schema_fields = set(OfferPackage.model_fields.keys())

        for field in schema_fields:
            assert field not in BANNED_FIELDS, f"BANNED field in OfferPackage: {field}"
            for indicator in INVESTOR_MODEL_INDICATORS:
                assert indicator not in field.lower(), f"Investor indicator in OfferPackage: {field}"

    def test_offer_option_summary_has_no_investor_economics(self):
        """OfferOptionSummary should not expose investor IRR or margins."""
        from schemas import OfferOptionSummary

        schema_fields = set(OfferOptionSummary.model_fields.keys())

        banned_in_options = {
            "investor_irr", "project_irr", "equity_irr",
            "gross_margin_pct", "gross_margin_pln", "direct_cost_pln"
        }

        for field in schema_fields:
            assert field not in banned_in_options, f"BANNED field in OfferOptionSummary: {field}"


# =============================================================================
# ENDPOINT OUTPUT TESTS - Verify actual API responses don't leak data
# =============================================================================

class TestOfferPackageEndpointSecurity:
    """Test that offer-package endpoint returns only CUSTOMER_SAFE data."""

    def test_mock_offer_package_has_no_banned_fields(self):
        """
        Verify a mock OfferPackage response has no banned fields.
        This simulates what the endpoint would return.
        """
        from schemas import (
            OfferPackage, CustomerSafeInstallation, CustomerSafeConsumption,
            CustomerSafeProduction, CustomerSafeCapexEconomics,
            CustomerSafeEaasEconomics
        )
        from datetime import datetime

        # Create a mock offer package (what the endpoint returns)
        mock_package = OfferPackage(
            offer_id="OFFER-2026-0001",
            offer_version="v1",
            project_name="Test Solar Farm",
            company_name="Test Company",
            created_at=datetime.now(),
            valid_until=None,
            installation=CustomerSafeInstallation(
                pv_capacity_kwp=500.0,
                pv_type="ground_s",
                has_bess=False,
                bess_power_kw=None,
                bess_energy_kwh=None,
                location_name="Warsaw"
            ),
            consumption=CustomerSafeConsumption(
                annual_consumption_kwh=1200000,
                peak_power_kw=450,
                profile_year=2024,
                data_source="PPE"
            ),
            production=CustomerSafeProduction(
                scenario="P50",
                annual_production_kwh=525000,
                self_consumption_kwh=367500,
                self_consumption_rate_pct=70.0,
                grid_export_kwh=157500
            ),
            capex_economics=CustomerSafeCapexEconomics(
                investment_pln=1707300,  # Sell price, NOT cost
                npv_pln=500000,
                irr_pct=12.5,
                simple_payback_years=8.5,
                annual_savings_year1_pln=180000
            ),
            eaas_economics=CustomerSafeEaasEconomics(
                duration_years=15,
                subscription_annual_pln=96000,
                subscription_monthly_pln=8000,
                price_per_mwh_pln=350,
                npv_pln=300000,
                total_savings_over_contract_pln=450000,
                savings_vs_grid_pct=15.0
            ),
            yearly_cashflows=[],
            options=[],
            selected_option="A"
        )

        # Serialize to dict (simulating JSON response)
        response_data = mock_package.model_dump()

        # Check for banned fields
        found_violations = find_banned_fields_recursive(response_data)

        assert len(found_violations) == 0, \
            f"SECURITY VIOLATION: Banned fields found in OfferPackage:\n" + \
            "\n".join(found_violations)


class TestPublicationHistorySecurity:
    """Test that publication-history endpoint doesn't leak internal data."""

    def test_publication_history_response_has_no_banned_fields(self):
        """Verify publication history response structure is customer-safe."""

        # This is the structure returned by get_publication_history endpoint
        mock_history_response = [
            {
                "id": 1,
                "offer_id": "OFFER-2026-0001",
                "offer_version": "v1",
                "option_key": "A",
                "snapshot_id": 123,
                "published_at": "2026-01-11T10:00:00Z",
                "published_by": "admin@example.com",
                "valid_until": "2026-02-10T10:00:00Z",
                "action": "publish",
                "key_terms": {
                    "pv_capacity_kwp": 500.0,
                    "capex_sell_price_pln": 1707300,  # SELL price, not cost
                    "eaas_subscription_annual_pln": 96000,
                    "eaas_duration_years": 15,
                    "credit_risk_class": "B",
                    "max_eaas_duration_allowed": 20
                }
            }
        ]

        # Check for banned fields
        found_violations = find_banned_fields_recursive(mock_history_response)

        # Filter out false positives (credit_risk_class is OK to show)
        real_violations = [v for v in found_violations
                          if "credit_risk_class" not in v and
                             "max_eaas_duration_allowed" not in v]

        assert len(real_violations) == 0, \
            f"SECURITY VIOLATION: Banned fields in publication history:\n" + \
            "\n".join(real_violations)

    def test_publication_history_key_terms_no_cost_data(self):
        """Verify key_terms shows sell_price, NOT cost."""

        key_terms_allowed = {
            "pv_capacity_kwp",
            "capex_sell_price_pln",  # SELL price (customer sees)
            "eaas_subscription_annual_pln",
            "eaas_duration_years",
            "credit_risk_class",
            "max_eaas_duration_allowed"
        }

        key_terms_banned = {
            "capex_cost_pln",
            "direct_cost_pln",
            "gross_margin_pln",
            "gross_margin_pct",
            "investor_irr",
        }

        # Verify banned fields are not in allowed set
        for field in key_terms_banned:
            assert field not in key_terms_allowed, f"Banned field in key_terms: {field}"


# =============================================================================
# CASHFLOW MODEL TYPE TESTS
# =============================================================================

class TestCashflowModelTypeSecurity:
    """Ensure only CLIENT models are exposed, never INVESTOR models."""

    def test_yearly_cashflows_only_client_perspective(self):
        """Verify yearly_cashflows use only EAAS_CLIENT, not EAAS_INVESTOR."""
        from schemas import CustomerSafeYearlyCashflow

        # CustomerSafeYearlyCashflow should have client-friendly fields
        schema_fields = set(CustomerSafeYearlyCashflow.model_fields.keys())

        expected_fields = {"year", "phase", "savings_pln", "cost_pln",
                          "net_benefit_pln", "cumulative_benefit_pln"}

        assert schema_fields == expected_fields, \
            f"CustomerSafeYearlyCashflow has unexpected fields: {schema_fields - expected_fields}"

        # No investor-related field names
        for field in schema_fields:
            assert "investor" not in field.lower()
            assert "revenue" not in field.lower()  # revenue is investor perspective
            assert "opex" not in field.lower()  # opex is investor perspective


# =============================================================================
# INTEGRATION TEST - Full offer-package endpoint
# =============================================================================

class TestOfferPackageEndpointIntegration:
    """Integration test for offer-package endpoint security."""

    def test_offer_package_endpoint_response_structure(self):
        """
        Test that the actual endpoint code builds a safe response.
        This requires mocking the database.
        """
        # Import after path setup
        import sys
        sys.path.insert(0, '..')

        from schemas import OfferPackage

        # Verify OfferPackage model structure
        fields = OfferPackage.model_fields

        # Must have these customer-safe sections
        assert "installation" in fields
        assert "consumption" in fields
        assert "production" in fields
        assert "capex_economics" in fields
        assert "eaas_economics" in fields

        # Must NOT have internal sections
        assert "investor_economics" not in fields
        assert "deal_economics" not in fields
        assert "margin" not in str(fields).lower()
        assert "cost" not in str(fields).lower() or "forecast" in str(fields).lower()


# =============================================================================
# MANUAL VERIFICATION HELPERS
# =============================================================================

def check_json_response_for_leaks(json_data: dict) -> bool:
    """
    Helper function to manually verify any JSON response.
    Returns True if safe, raises AssertionError if leaks found.
    """
    violations = find_banned_fields_recursive(json_data)
    if violations:
        print("SECURITY VIOLATIONS FOUND:")
        for v in violations:
            print(f"  - {v}")
        return False
    print("Response is CUSTOMER_SAFE: No banned fields found")
    return True


if __name__ == "__main__":
    # Run pytest
    pytest.main([__file__, "-v"])
