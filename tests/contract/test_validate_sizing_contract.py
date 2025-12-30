"""
Contract tests for POST /validate/sizing endpoint (v1.4.0).

Tests verify:
- Response structure (passed, run_id, actual_kpis, diffs)
- Pass/fail logic based on tolerances
- KPI extraction from sizing response
- Tolerance configuration (default and per-field)
"""

import pytest
import requests

from ._api import post_json, load_smoke_payload


# API paths
VALIDATE_SIZING_PATH = "/validate/sizing"
BASE_URL = "http://localhost:8031"


def build_validate_request(expected_kpis, tolerances=None, scenario_id=None):
    """Build a validate sizing request with smoke payload."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    return {
        "request": payload,
        "expected_kpis": expected_kpis,
        "tolerances": tolerances,
        "scenario_id": scenario_id,
    }


class TestValidateSizingPresence:
    """Test endpoint presence and basic response structure."""

    def test_endpoint_exists(self):
        """Verify /validate/sizing endpoint exists."""
        # Use a minimal expected_kpis that should pass
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "passed" in response

    def test_response_has_passed_field(self):
        """Verify response has passed field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "passed" in response
        assert isinstance(response["passed"], bool)

    def test_response_has_run_id(self):
        """Verify response has run_id field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "run_id" in response
        assert isinstance(response["run_id"], str)

    def test_response_has_actual_kpis(self):
        """Verify response has actual_kpis field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "actual_kpis" in response
        assert isinstance(response["actual_kpis"], dict)

    def test_response_has_diffs(self):
        """Verify response has diffs field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "diffs" in response
        assert isinstance(response["diffs"], list)

    def test_response_has_failed_fields(self):
        """Verify response has failed_fields field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "failed_fields" in response
        assert isinstance(response["failed_fields"], list)

    def test_response_has_passed_fields(self):
        """Verify response has passed_fields field."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "passed_fields" in response
        assert isinstance(response["passed_fields"], list)


class TestValidateSizingScenarioId:
    """Test scenario_id echoing."""

    def test_scenario_id_echoed(self):
        """Verify scenario_id is echoed in response."""
        req = build_validate_request({"npv_pln": 0}, scenario_id="test-scenario-001")
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert response["scenario_id"] == "test-scenario-001"

    def test_scenario_id_null_when_not_provided(self):
        """Verify scenario_id is null when not provided."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert response["scenario_id"] is None


class TestValidateSizingActualKpis:
    """Test actual_kpis extraction."""

    def test_actual_kpis_has_recommended_variant(self):
        """Verify actual_kpis contains recommended_variant."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "recommended_variant" in response["actual_kpis"]
        assert response["actual_kpis"]["recommended_variant"] in ["small", "medium", "large"]

    def test_actual_kpis_has_npv_pln(self):
        """Verify actual_kpis contains npv_pln."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "npv_pln" in response["actual_kpis"]
        assert isinstance(response["actual_kpis"]["npv_pln"], (int, float))

    def test_actual_kpis_has_net_savings_pln(self):
        """Verify actual_kpis contains net_savings_pln."""
        req = build_validate_request({"net_savings_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "net_savings_pln" in response["actual_kpis"]

    def test_actual_kpis_has_payback_years(self):
        """Verify actual_kpis contains payback_years."""
        req = build_validate_request({"payback_years": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert "payback_years" in response["actual_kpis"]


class TestValidateSizingDiffs:
    """Test diffs structure and content."""

    def test_diffs_has_expected_fields(self):
        """Verify each diff has required fields."""
        req = build_validate_request({"npv_pln": 0, "payback_years": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)

        assert len(response["diffs"]) >= 2
        for diff in response["diffs"]:
            assert "field" in diff
            assert "expected" in diff
            assert "actual" in diff
            assert "abs_diff" in diff
            assert "abs_tol" in diff
            assert "rel_tol" in diff
            assert "pass" in diff

    def test_diffs_field_matches_expected_kpis(self):
        """Verify diffs are generated for fields in expected_kpis."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)

        diff_fields = [d["field"] for d in response["diffs"]]
        assert "npv_pln" in diff_fields


class TestValidateSizingPassFail:
    """Test pass/fail logic."""

    def test_passes_with_very_loose_tolerance(self):
        """Verify validation passes with very loose tolerance."""
        req = build_validate_request(
            {"npv_pln": 0},  # Expected 0, actual is non-zero
            tolerances={"default_abs": 1000000000.0, "default_rel": 0.0}  # 1B absolute tolerance
        )
        response = post_json(VALIDATE_SIZING_PATH, req)
        assert response["passed"] is True
        assert len(response["failed_fields"]) == 0

    def test_fails_with_impossible_tolerance(self):
        """Verify validation fails with impossible tolerance."""
        # Get actual NPV first
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)
        actual_npv = response["actual_kpis"]["npv_pln"]

        # Now expect a very different value with strict tolerance
        wrong_expected = actual_npv + 1000000  # 1M off
        req2 = build_validate_request(
            {"npv_pln": wrong_expected},
            tolerances={"default_abs": 0.0, "default_rel": 0.0}  # Zero tolerance
        )
        response2 = post_json(VALIDATE_SIZING_PATH, req2)
        assert response2["passed"] is False
        assert "npv_pln" in response2["failed_fields"]

    def test_passed_and_failed_fields_are_disjoint(self):
        """Verify passed_fields and failed_fields don't overlap."""
        req = build_validate_request({"npv_pln": 0, "payback_years": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)

        passed_set = set(response["passed_fields"])
        failed_set = set(response["failed_fields"])
        assert passed_set.isdisjoint(failed_set)

    def test_passed_and_failed_fields_cover_all_diffs(self):
        """Verify passed_fields + failed_fields covers all diff fields."""
        req = build_validate_request({"npv_pln": 0, "payback_years": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)

        diff_fields = set(d["field"] for d in response["diffs"])
        combined = set(response["passed_fields"]) | set(response["failed_fields"])
        assert diff_fields == combined


class TestValidateSizingTolerances:
    """Test tolerance configuration."""

    def test_default_tolerances_used(self):
        """Verify default tolerances are applied."""
        req = build_validate_request({"npv_pln": 0})
        response = post_json(VALIDATE_SIZING_PATH, req)

        # Check that default tolerances are used
        npv_diff = next(d for d in response["diffs"] if d["field"] == "npv_pln")
        assert npv_diff["abs_tol"] == 1.0  # default_abs
        assert npv_diff["rel_tol"] == 0.001  # default_rel

    def test_custom_default_tolerances(self):
        """Verify custom default tolerances are applied."""
        req = build_validate_request(
            {"npv_pln": 0},
            tolerances={"default_abs": 100.0, "default_rel": 0.05}
        )
        response = post_json(VALIDATE_SIZING_PATH, req)

        npv_diff = next(d for d in response["diffs"] if d["field"] == "npv_pln")
        assert npv_diff["abs_tol"] == 100.0
        assert npv_diff["rel_tol"] == 0.05

    def test_per_field_abs_tolerance(self):
        """Verify per-field absolute tolerance overrides default."""
        req = build_validate_request(
            {"npv_pln": 0, "payback_years": 0},
            tolerances={
                "default_abs": 1.0,
                "per_field_abs": {"npv_pln": 500.0}
            }
        )
        response = post_json(VALIDATE_SIZING_PATH, req)

        npv_diff = next(d for d in response["diffs"] if d["field"] == "npv_pln")
        payback_diff = next(d for d in response["diffs"] if d["field"] == "payback_years")

        assert npv_diff["abs_tol"] == 500.0  # per-field override
        assert payback_diff["abs_tol"] == 1.0  # default

    def test_per_field_rel_tolerance(self):
        """Verify per-field relative tolerance overrides default."""
        req = build_validate_request(
            {"npv_pln": 0, "payback_years": 0},
            tolerances={
                "default_rel": 0.001,
                "per_field_rel": {"payback_years": 0.1}
            }
        )
        response = post_json(VALIDATE_SIZING_PATH, req)

        npv_diff = next(d for d in response["diffs"] if d["field"] == "npv_pln")
        payback_diff = next(d for d in response["diffs"] if d["field"] == "payback_years")

        assert npv_diff["rel_tol"] == 0.001  # default
        assert payback_diff["rel_tol"] == 0.1  # per-field override


class TestValidateSizingInvalidRequest:
    """Test error handling for invalid requests."""

    def test_invalid_sizing_request_returns_422(self):
        """Verify invalid sizing request returns 422."""
        req = {
            "request": {"invalid_field": "value"},  # Invalid sizing request
            "expected_kpis": {"npv_pln": 0},
        }
        response = requests.post(f"{BASE_URL}{VALIDATE_SIZING_PATH}", json=req)
        assert response.status_code == 422
