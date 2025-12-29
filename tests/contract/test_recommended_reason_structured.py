"""
Contract tests for structured recommended_reason fields.

These tests verify:
- recommended_reason_code is present and valid enum
- recommended_reason_metric matches objective
- recommended_reason_value is numeric
- recommended_reason_unit is appropriate for metric
- Structured fields are consistent with objective_used
"""
import pytest
import requests


VALID_REASON_CODES = {
    "npv_max",
    "payback_min",
    "self_consumption_max",
    "peak_reduction_max",
    "efc_utilization_max",
    "constrained_fallback",
}

VALID_METRICS = {
    "npv_pln",
    "payback_years",
    "self_consumption_pct",
    "peak_reduction_pct",
    "efc_total",
}

VALID_UNITS = {"PLN", "years", "%", "cycles"}


class TestStructuredReasonPresence:
    """Test that structured reason fields are present."""

    def test_structured_fields_present_in_response(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Structured reason fields should be present in response."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # All structured fields should be present
        assert "recommended_reason_code" in data, "recommended_reason_code missing"
        assert "recommended_reason_metric" in data, "recommended_reason_metric missing"
        assert "recommended_reason_value" in data, "recommended_reason_value missing"
        assert "recommended_reason_unit" in data, "recommended_reason_unit missing"

    def test_structured_fields_not_null(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Structured reason fields should not be null when variants exist."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()

        # Should have variants
        assert len(data.get("variants", [])) > 0, "No variants in response"

        # Fields should not be null
        assert data["recommended_reason_code"] is not None, "code is null"
        assert data["recommended_reason_metric"] is not None, "metric is null"
        assert data["recommended_reason_value"] is not None, "value is null"
        assert data["recommended_reason_unit"] is not None, "unit is null"


class TestStructuredReasonCodeEnum:
    """Test that recommended_reason_code is valid enum."""

    def test_code_is_valid_enum(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_code should be one of valid enum values."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        code = data.get("recommended_reason_code")

        assert code in VALID_REASON_CODES, (
            f"recommended_reason_code '{code}' not in valid values: {VALID_REASON_CODES}"
        )

    def test_code_matches_objective_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is NPV (default), code should be npv_max."""
        # Ensure no optimization config
        request = {**minimal_sizing_request}
        if "optimization" in request:
            del request["optimization"]

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        code = data.get("recommended_reason_code")

        assert code == "npv_max", (
            f"Expected 'npv_max' for default NPV objective, got '{code}'"
        )

    def test_code_matches_objective_payback(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is payback, code should be payback_min."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "payback"}
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )

        data = response.json()
        code = data.get("recommended_reason_code")

        assert code == "payback_min", (
            f"Expected 'payback_min' for payback objective, got '{code}'"
        )


class TestStructuredReasonMetric:
    """Test that recommended_reason_metric is valid."""

    def test_metric_is_valid(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_metric should be one of valid values."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        metric = data.get("recommended_reason_metric")

        assert metric in VALID_METRICS, (
            f"recommended_reason_metric '{metric}' not in valid values: {VALID_METRICS}"
        )

    def test_metric_matches_npv_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is NPV, metric should be npv_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        metric = data.get("recommended_reason_metric")

        assert metric == "npv_pln", (
            f"Expected 'npv_pln' for NPV objective, got '{metric}'"
        )


class TestStructuredReasonValue:
    """Test that recommended_reason_value is numeric."""

    def test_value_is_numeric(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_value should be a number."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        value = data.get("recommended_reason_value")

        assert isinstance(value, (int, float)), (
            f"recommended_reason_value should be numeric, got {type(value)}: {value}"
        )

    def test_value_matches_npv_for_npv_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is NPV, value should match recommended variant's NPV."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        value = data.get("recommended_reason_value")

        # Find recommended variant
        variants = data.get("variants", [])
        recommended = [v for v in variants if v.get("is_recommended")]
        assert len(recommended) == 1, "Should have exactly one recommended variant"

        expected_npv = recommended[0]["npv_pln"]

        assert abs(value - expected_npv) < 0.01, (
            f"recommended_reason_value {value} should match NPV {expected_npv}"
        )


class TestStructuredReasonUnit:
    """Test that recommended_reason_unit is valid."""

    def test_unit_is_valid(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_unit should be one of valid values."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        unit = data.get("recommended_reason_unit")

        assert unit in VALID_UNITS, (
            f"recommended_reason_unit '{unit}' not in valid values: {VALID_UNITS}"
        )

    def test_unit_is_pln_for_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """When objective is NPV, unit should be PLN."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        unit = data.get("recommended_reason_unit")

        assert unit == "PLN", f"Expected 'PLN' for NPV objective, got '{unit}'"


class TestStructuredReasonConsistency:
    """Test consistency between structured fields and other response data."""

    def test_code_consistent_with_objective_used(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_code should be consistent with objective_used."""
        # Map of objective_used -> expected code
        expected_map = {
            "npv": "npv_max",
            "payback": "payback_min",
            "self_consumption": "self_consumption_max",
            "peak_reduction": "peak_reduction_max",
            "efc_utilization": "efc_utilization_max",
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        objective_used = data.get("objective_used")
        code = data.get("recommended_reason_code")

        expected_code = expected_map.get(objective_used)
        assert code == expected_code, (
            f"For objective_used='{objective_used}', expected code='{expected_code}', "
            f"got '{code}'"
        )
