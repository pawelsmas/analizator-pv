"""
Contract tests for top_variants field in sizing response.

These tests verify:
- top_variants is present when variants exist
- top_variants is sorted by score (highest first)
- top_variants contains max 3 items
- recommended_variant is always first in top_variants
"""
import pytest
import requests


class TestTopVariantsPresence:
    """Test that top_variants is present in response."""

    def test_top_variants_present_in_response(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants should be present when variants exist."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have variants
        assert len(data.get("variants", [])) > 0

        # top_variants should be present
        assert "top_variants" in data, "top_variants must be in response"
        assert data["top_variants"] is not None, "top_variants cannot be null"
        assert isinstance(data["top_variants"], list)


class TestTopVariantsOrder:
    """Test that top_variants is sorted correctly."""

    def test_recommended_is_first_in_top_variants(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Recommended variant should always be first in top_variants."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])
        recommended = data.get("recommended_variant")

        # Recommended should be first in top_variants
        assert len(top_variants) > 0, "top_variants should not be empty"
        assert top_variants[0] == recommended, (
            f"First top variant should be recommended. "
            f"Got {top_variants[0]}, expected {recommended}"
        )

    def test_top_variants_sorted_by_score(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants should be sorted by score (highest first)."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])
        variants = data.get("variants", [])

        # Build a map of variant -> score
        score_map = {v["variant"]: v["score"] for v in variants}

        # Verify top_variants are in descending score order
        for i in range(len(top_variants) - 1):
            current_score = score_map.get(top_variants[i], 0)
            next_score = score_map.get(top_variants[i + 1], 0)
            assert current_score >= next_score, (
                f"top_variants not sorted by score: "
                f"{top_variants[i]} (score={current_score}) should be >= "
                f"{top_variants[i+1]} (score={next_score})"
            )


class TestTopVariantsSize:
    """Test that top_variants has correct size."""

    def test_top_variants_max_three(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants should have at most 3 items."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])

        assert len(top_variants) <= 3, (
            f"top_variants should have at most 3 items, got {len(top_variants)}"
        )

    def test_top_variants_matches_variants_count_when_less_than_three(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants should equal variants count when fewer than 3."""
        # Use durations that result in different number of variants
        request = {
            **minimal_sizing_request,
            "durations_h": [2.0],  # Only 1 variant
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])
        variants = data.get("variants", [])

        assert len(top_variants) == min(len(variants), 3), (
            f"top_variants should have {min(len(variants), 3)} items, "
            f"got {len(top_variants)}"
        )
