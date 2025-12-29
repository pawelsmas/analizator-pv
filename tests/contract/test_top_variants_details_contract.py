"""
Contract tests for top_variants_details field in sizing response.

These tests verify:
- top_variants_details is present when variants exist
- top_variants_details has same length as top_variants
- First element is the recommended variant
- Each detail has required fields with correct types
- Details.variant matches names in top_variants
"""
import pytest
import requests


class TestTopVariantsDetailsPresence:
    """Test that top_variants_details is present in response."""

    def test_top_variants_details_present(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants_details should be present when variants exist."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have variants
        assert len(data.get("variants", [])) > 0, "No variants in response"

        # top_variants_details should be present
        assert "top_variants_details" in data, "top_variants_details missing"
        assert data["top_variants_details"] is not None, "top_variants_details is null"
        assert isinstance(data["top_variants_details"], list)

    def test_top_variants_details_not_empty(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants_details should not be empty when variants exist."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])

        assert len(details) > 0, "top_variants_details should not be empty"


class TestTopVariantsDetailsLength:
    """Test that top_variants_details has correct length."""

    def test_details_length_matches_top_variants(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants_details length should match top_variants."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])
        details = data.get("top_variants_details", [])

        assert len(details) == len(top_variants), (
            f"top_variants_details has {len(details)} items, "
            f"but top_variants has {len(top_variants)}"
        )

    def test_details_max_three_items(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants_details should have at most 3 items."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])

        assert len(details) <= 3, (
            f"top_variants_details should have at most 3 items, got {len(details)}"
        )


class TestTopVariantsDetailsFirstElement:
    """Test that first element is the recommended variant."""

    def test_first_detail_is_recommended(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """First element should be the recommended variant."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])
        recommended = data.get("recommended_variant")

        assert len(details) > 0, "No details in response"
        assert details[0]["variant"] == recommended, (
            f"First detail.variant '{details[0]['variant']}' should match "
            f"recommended_variant '{recommended}'"
        )


class TestTopVariantsDetailsFields:
    """Test that each detail has required fields."""

    def test_detail_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Each detail should have variant, score, npv_pln, payback_years, net_savings_pln."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])

        required_fields = {"variant", "score", "npv_pln", "payback_years", "net_savings_pln"}

        for i, detail in enumerate(details):
            for field in required_fields:
                assert field in detail, (
                    f"Detail [{i}] missing required field '{field}'"
                )

    def test_detail_fields_have_correct_types(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Detail fields should have correct types."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])

        for i, detail in enumerate(details):
            assert isinstance(detail["variant"], str), (
                f"Detail [{i}].variant should be string"
            )
            assert isinstance(detail["score"], (int, float)), (
                f"Detail [{i}].score should be numeric"
            )
            assert isinstance(detail["npv_pln"], (int, float)), (
                f"Detail [{i}].npv_pln should be numeric"
            )
            assert isinstance(detail["payback_years"], (int, float)), (
                f"Detail [{i}].payback_years should be numeric"
            )
            assert isinstance(detail["net_savings_pln"], (int, float)), (
                f"Detail [{i}].net_savings_pln should be numeric"
            )


class TestTopVariantsDetailsConsistency:
    """Test consistency between top_variants and top_variants_details."""

    def test_detail_variants_match_top_variants(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Detail variant names should match top_variants list."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        top_variants = data.get("top_variants", [])
        details = data.get("top_variants_details", [])

        detail_variants = [d["variant"] for d in details]

        assert detail_variants == top_variants, (
            f"Detail variants {detail_variants} don't match "
            f"top_variants {top_variants}"
        )

    def test_details_sorted_by_score(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """top_variants_details should be sorted by score (highest first)."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])

        for i in range(len(details) - 1):
            assert details[i]["score"] >= details[i + 1]["score"], (
                f"Details not sorted by score: "
                f"details[{i}].score={details[i]['score']} < "
                f"details[{i+1}].score={details[i+1]['score']}"
            )


class TestTopVariantsDetailsValues:
    """Test that detail values match variant data."""

    def test_detail_npv_matches_variant(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Detail NPV should match the corresponding variant's NPV."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        data = response.json()
        details = data.get("top_variants_details", [])
        variants = data.get("variants", [])

        # Build variant name -> NPV map
        variant_npv = {v["variant"]: v["npv_pln"] for v in variants}

        for detail in details:
            expected_npv = variant_npv.get(detail["variant"])
            assert expected_npv is not None, (
                f"Variant '{detail['variant']}' not found in variants"
            )
            assert abs(detail["npv_pln"] - expected_npv) < 0.01, (
                f"Detail NPV {detail['npv_pln']} doesn't match "
                f"variant NPV {expected_npv}"
            )
