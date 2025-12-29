"""
Contract tests for objective switching behavior.

These tests verify that changing the optimization objective:
1. Changes the objective_used field to match the request
2. Changes the recommended_reason_code to match the objective
3. Changes the recommended_reason_metric and unit accordingly
4. Changes the top_variants ordering based on objective score

Key contract:
- Same payload + objective=npv -> recommended based on highest NPV
- Same payload + objective=payback -> recommended based on lowest payback
- reason_value matches the recommended variant's metric value
"""
import pytest
import requests


class TestObjectiveSwitchRecommendation:
    """Test that objective switch affects recommendation selection."""

    def test_objective_used_matches_request(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """objective_used should always match the requested objective."""
        objectives = ["npv", "payback"]

        for objective in objectives:
            request = {
                **minimal_sizing_request,
                "optimization": {"objective": objective},
            }

            response = requests.post(
                f"{bess_dispatch_url}/sizing",
                json=request,
                timeout=120,
            )

            assert response.status_code == 200
            data = response.json()

            assert data.get("objective_used") == objective, (
                f"objective_used should be '{objective}', "
                f"got '{data.get('objective_used')}'"
            )

    def test_reason_code_matches_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_code should match the optimization objective."""
        objective_to_code = {
            "npv": "npv_max",
            "payback": "payback_min",
            "self_consumption": "self_consumption_max",
            "peak_reduction": "peak_reduction_max",
            "efc_utilization": "efc_utilization_max",
        }

        for objective, expected_code in objective_to_code.items():
            request = {
                **minimal_sizing_request,
                "optimization": {"objective": objective},
            }

            response = requests.post(
                f"{bess_dispatch_url}/sizing",
                json=request,
                timeout=120,
            )

            assert response.status_code == 200
            data = response.json()

            actual_code = data.get("recommended_reason_code")
            assert actual_code == expected_code, (
                f"objective={objective}: expected code '{expected_code}', "
                f"got '{actual_code}'"
            )


class TestObjectiveSwitchMetrics:
    """Test that objective switch changes the reason metric."""

    def test_reason_metric_matches_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_metric should match the optimization objective."""
        objective_to_metric = {
            "npv": "npv_pln",
            "payback": "payback_years",
        }

        for objective, expected_metric in objective_to_metric.items():
            request = {
                **minimal_sizing_request,
                "optimization": {"objective": objective},
            }

            response = requests.post(
                f"{bess_dispatch_url}/sizing",
                json=request,
                timeout=120,
            )

            assert response.status_code == 200
            data = response.json()

            actual_metric = data.get("recommended_reason_metric")
            assert actual_metric == expected_metric, (
                f"objective={objective}: expected metric '{expected_metric}', "
                f"got '{actual_metric}'"
            )

    def test_reason_unit_matches_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """recommended_reason_unit should match the optimization objective."""
        objective_to_unit = {
            "npv": "PLN",
            "payback": "years",
        }

        for objective, expected_unit in objective_to_unit.items():
            request = {
                **minimal_sizing_request,
                "optimization": {"objective": objective},
            }

            response = requests.post(
                f"{bess_dispatch_url}/sizing",
                json=request,
                timeout=120,
            )

            assert response.status_code == 200
            data = response.json()

            actual_unit = data.get("recommended_reason_unit")
            assert actual_unit == expected_unit, (
                f"objective={objective}: expected unit '{expected_unit}', "
                f"got '{actual_unit}'"
            )


class TestObjectiveSwitchTopVariants:
    """Test that objective switch affects top_variants ordering."""

    def test_top_variants_sorted_by_objective(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        top_variants should be sorted by objective score.

        For NPV: higher is better -> descending by NPV
        For payback: lower is better -> ascending by payback
        """
        request_npv = {
            **minimal_sizing_request,
            "optimization": {"objective": "npv"},
        }

        request_payback = {
            **minimal_sizing_request,
            "optimization": {"objective": "payback"},
        }

        # Get NPV-optimized response
        response_npv = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request_npv,
            timeout=120,
        )
        assert response_npv.status_code == 200
        data_npv = response_npv.json()

        # Get payback-optimized response
        response_payback = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request_payback,
            timeout=120,
        )
        assert response_payback.status_code == 200
        data_payback = response_payback.json()

        # Both should have top_variants_details sorted by their respective scores
        details_npv = data_npv.get("top_variants_details", [])
        details_payback = data_payback.get("top_variants_details", [])

        # NPV: scores should be descending
        for i in range(len(details_npv) - 1):
            assert details_npv[i]["score"] >= details_npv[i + 1]["score"], (
                f"NPV top_variants not sorted by score: "
                f"{details_npv[i]['score']} < {details_npv[i + 1]['score']}"
            )

        # Payback: scores should also be descending (higher score = better)
        # Note: For payback, score is calculated such that lower payback = higher score
        for i in range(len(details_payback) - 1):
            assert details_payback[i]["score"] >= details_payback[i + 1]["score"], (
                f"Payback top_variants not sorted by score: "
                f"{details_payback[i]['score']} < {details_payback[i + 1]['score']}"
            )


class TestObjectiveSwitchReasonValue:
    """Test that reason value matches the recommended variant's metric."""

    def test_npv_reason_value_matches_variant_npv(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """For NPV objective, reason_value should equal recommended variant's NPV."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "npv"},
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Get recommended variant's NPV
        recommended_name = data.get("recommended_variant")
        variants = data.get("variants", [])
        recommended = next(
            (v for v in variants if v.get("variant") == recommended_name),
            None
        )

        assert recommended is not None, "Could not find recommended variant"

        expected_value = recommended.get("npv_pln")
        actual_value = data.get("recommended_reason_value")

        assert abs(actual_value - expected_value) < 1.0, (
            f"reason_value {actual_value} should match variant NPV {expected_value}"
        )

    def test_payback_reason_value_matches_variant_payback(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """For payback objective, reason_value should equal recommended variant's payback."""
        request = {
            **minimal_sizing_request,
            "optimization": {"objective": "payback"},
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Get recommended variant's payback
        recommended_name = data.get("recommended_variant")
        variants = data.get("variants", [])
        recommended = next(
            (v for v in variants if v.get("variant") == recommended_name),
            None
        )

        assert recommended is not None, "Could not find recommended variant"

        expected_value = recommended.get("simple_payback_years")
        actual_value = data.get("recommended_reason_value")

        assert abs(actual_value - expected_value) < 0.1, (
            f"reason_value {actual_value} should match variant payback {expected_value}"
        )
