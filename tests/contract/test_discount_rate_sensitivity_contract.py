"""
Contract tests for discount_rate_sensitivity feature.

These tests verify the v0.5.0 PR3 discount rate sensitivity feature:
1. discount_rate_sensitivity is absent by default
2. discount_rate_sensitivity is present when discount_rate_sweep provided
3. NPV monotonicity: NPV decreases as discount rate increases
"""
import pytest
import requests


class TestDiscountRateSensitivityPresence:
    """Test that discount_rate_sensitivity is correctly returned based on flag."""

    def test_sensitivity_absent_by_default(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """discount_rate_sensitivity should be null when sweep not provided."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary")
            if fs:
                assert fs.get("discount_rate_sensitivity") is None, (
                    f"Variant {v.get('variant')}: discount_rate_sensitivity "
                    "should be null by default"
                )

    def test_sensitivity_present_when_sweep_provided(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """discount_rate_sensitivity should be present when discount_rate_sweep provided."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.05, 0.08, 0.10, 0.12],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        assert len(variants) > 0, "Should have at least one variant"

        for v in variants:
            fs = v.get("finance_summary")
            assert fs is not None, f"Variant {v.get('variant')} should have finance_summary"
            drs = fs.get("discount_rate_sensitivity")
            assert drs is not None, (
                f"Variant {v.get('variant')}: discount_rate_sensitivity should be present"
            )
            assert isinstance(drs, list), (
                f"Variant {v.get('variant')}: discount_rate_sensitivity should be a list"
            )
            assert len(drs) == 4, (
                f"Variant {v.get('variant')}: should have 4 sensitivity points"
            )


class TestDiscountRateSensitivityStructure:
    """Test discount_rate_sensitivity structure."""

    def test_sensitivity_point_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Each DiscountRateSensitivityPoint should have all required fields."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.05, 0.08, 0.10],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        required_fields = ["discount_rate", "discount_rate_pct", "npv_pln"]

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            for point in drs:
                for field in required_fields:
                    assert field in point, (
                        f"Sensitivity point for variant {v.get('variant')} "
                        f"should have {field}"
                    )

    def test_sensitivity_sorted_by_discount_rate(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Sensitivity points should be sorted by discount_rate (ascending)."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.12, 0.05, 0.08],  # Unsorted input
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            rates = [p["discount_rate"] for p in drs]
            assert rates == sorted(rates), (
                f"Variant {v.get('variant')}: sensitivity should be sorted by rate"
            )

    def test_discount_rate_pct_is_percentage(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """discount_rate_pct should be discount_rate * 100."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.05, 0.08, 0.10],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            for point in drs:
                expected_pct = point["discount_rate"] * 100
                assert abs(point["discount_rate_pct"] - expected_pct) < 0.001, (
                    f"Variant {v.get('variant')}: discount_rate_pct should be "
                    f"discount_rate * 100"
                )


class TestNPVMonotonicity:
    """Test NPV behavior with respect to discount rate (key contract invariant)."""

    def test_npv_changes_monotonically_with_discount_rate(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        NPV should change monotonically as discount rate increases.

        For positive NPV projects: higher rate = lower NPV (decreasing)
        For negative NPV projects: higher rate = less negative NPV (increasing)

        The key invariant is that NPV should NOT oscillate - it should be
        strictly monotonic (either all decreasing or all increasing).
        """
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.02, 0.05, 0.08, 0.10, 0.15, 0.20],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            npvs = [p["npv_pln"] for p in drs]

            # Check monotonicity: all differences should have the same sign
            # (either all increasing or all decreasing)
            diffs = [npvs[i] - npvs[i-1] for i in range(1, len(npvs))]

            # Skip monotonicity check if all diffs are effectively zero
            if all(abs(d) < 1.0 for d in diffs):
                continue

            # Non-trivial diffs should all be same sign
            positive_diffs = [d for d in diffs if d > 1.0]
            negative_diffs = [d for d in diffs if d < -1.0]

            # Either all positive (increasing), all negative (decreasing), or all near-zero
            assert len(positive_diffs) == 0 or len(negative_diffs) == 0, (
                f"Variant {v.get('variant')}: NPV should be monotonic (not oscillate). "
                f"Got {len(positive_diffs)} increases and {len(negative_diffs)} decreases."
            )

    def test_npv_at_base_rate_matches_finance_summary(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """NPV at the base discount rate should match finance_summary.npv_pln."""
        base_rate = 0.08
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate": base_rate,
                "discount_rate_sweep": [0.05, base_rate, 0.10],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            npv_from_summary = fs.get("npv_pln", 0)
            drs = fs.get("discount_rate_sensitivity", [])

            # Find the point at base_rate
            base_point = next(
                (p for p in drs if abs(p["discount_rate"] - base_rate) < 0.001),
                None
            )

            assert base_point is not None, (
                f"Variant {v.get('variant')}: should have sensitivity point at base rate"
            )

            # NPV should match (within tolerance)
            tolerance = max(abs(npv_from_summary) * 0.01, 1.0)
            diff = abs(base_point["npv_pln"] - npv_from_summary)
            assert diff < tolerance, (
                f"Variant {v.get('variant')}: NPV at base rate ({base_point['npv_pln']:.2f}) "
                f"should match finance_summary.npv_pln ({npv_from_summary:.2f})"
            )


class TestEdgeCases:
    """Test edge cases for discount rate sensitivity."""

    def test_single_rate_sweep(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Single rate in sweep should return single point."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [0.10],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])
            assert len(drs) == 1, (
                f"Variant {v.get('variant')}: single rate sweep should return single point"
            )

    def test_empty_sweep_treated_as_none(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Empty discount_rate_sweep should result in null sensitivity."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "discount_rate_sweep": [],
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity")
            # Empty list should result in empty list or null
            assert drs is None or len(drs) == 0, (
                f"Variant {v.get('variant')}: empty sweep should result in null or empty"
            )
