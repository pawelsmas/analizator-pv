"""
Contract tests for /validate pricing_debug (v2.0.0 PR4).

Tests verify:
- pricing_debug field is present in response
- pricing_mode shows 'generated' or 'override'
- price_hash is 64-char hex string
- top_cost_buckets has correct structure and percentages sum to ~100%
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_validate_request(n_hours: int = 24):
    """Create a basic /validate/sizing request."""
    return {
        "request": {
            "pv_generation_kw": [50.0] * n_hours,
            "load_kw": [30.0] * n_hours,
            "interval_minutes": 60,
            "battery_power_kw": 50.0,
            "battery_energy_kwh": 100.0,
            "mode": "pv_surplus",
            "prices": {
                "import_price_pln_mwh": 800.0,
                "export_price_pln_mwh": 400.0,
            },
        },
        "expected_kpis": {
            "npv_pln": 0,  # Dummy expected value
        },
        "tolerances": {
            "default_abs": 1000000,  # Large tolerance to pass
            "default_rel": 1.0,
        },
    }


class TestPricingDebugPresent:
    """Tests for pricing_debug field presence."""

    def test_pricing_debug_present_in_response(self):
        """Verify pricing_debug is present in /validate response."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200, f"Validate failed: {response.text}"
        result = response.json()

        assert "pricing_debug" in result, "pricing_debug should be present in response"
        assert result["pricing_debug"] is not None, "pricing_debug should not be None"

    def test_pricing_mode_is_generated(self):
        """Verify pricing_mode is 'generated' for normal requests."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        assert pricing_debug.get("pricing_mode") == "generated", \
            f"Expected pricing_mode='generated', got '{pricing_debug.get('pricing_mode')}'"

    def test_price_hash_present(self):
        """Verify price_hash is present and valid."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        price_hash = pricing_debug.get("price_hash")

        assert price_hash is not None, "price_hash should be present"
        assert len(price_hash) == 64, f"price_hash should be 64 chars, got {len(price_hash)}"
        assert all(c in '0123456789abcdef' for c in price_hash), "price_hash should be hex"


class TestTopCostBuckets:
    """Tests for top_cost_buckets field."""

    def test_top_cost_buckets_present(self):
        """Verify top_cost_buckets is present and non-empty."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        buckets = pricing_debug.get("top_cost_buckets", [])

        assert len(buckets) > 0, "top_cost_buckets should not be empty"

    def test_cost_bucket_structure(self):
        """Verify each cost bucket has required fields."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        buckets = pricing_debug.get("top_cost_buckets", [])

        for bucket in buckets:
            assert "category" in bucket, "Bucket should have 'category' field"
            assert "sum_pln" in bucket, "Bucket should have 'sum_pln' field"
            assert "pct_of_total" in bucket, "Bucket should have 'pct_of_total' field"

    def test_cost_bucket_categories_valid(self):
        """Verify cost bucket categories are valid."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        buckets = pricing_debug.get("top_cost_buckets", [])

        valid_categories = {"import", "export_revenue", "other_fees", "unserved_penalty"}
        for bucket in buckets:
            assert bucket["category"] in valid_categories, \
                f"Invalid category: {bucket['category']}"

    def test_percentages_sum_to_100(self):
        """Verify bucket percentages sum to approximately 100%."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        buckets = pricing_debug.get("top_cost_buckets", [])

        total_pct = sum(b["pct_of_total"] for b in buckets)
        assert abs(total_pct - 100.0) < 1.0, \
            f"Percentages should sum to ~100%, got {total_pct}%"

    def test_buckets_sorted_by_absolute_value(self):
        """Verify buckets are sorted by absolute sum descending."""
        request = create_validate_request()
        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response.status_code == 200
        result = response.json()

        pricing_debug = result.get("pricing_debug", {})
        buckets = pricing_debug.get("top_cost_buckets", [])

        if len(buckets) > 1:
            abs_sums = [abs(b["sum_pln"]) for b in buckets]
            for i in range(len(abs_sums) - 1):
                assert abs_sums[i] >= abs_sums[i + 1], \
                    "Buckets should be sorted by absolute value descending"


class TestPricingDebugWithOverride:
    """Tests for pricing_debug with price override."""

    def test_pricing_mode_override(self):
        """Verify pricing_mode is 'override' when override provided."""
        n_hours = 24
        request = create_validate_request(n_hours)

        # Add price override
        request["request"]["price_timeseries_override"] = {
            "import_price_pln_per_mwh": [1000.0] * n_hours,
            "export_price_pln_per_mwh": [500.0] * n_hours,
            "step_minutes": 60,
            "steps": n_hours,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-01T00:00:00",
            "period_end": f"2025-01-01T{n_hours-1:02d}:00:00",
        }

        response = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)
        assert response.status_code == 200, f"Validate failed: {response.text}"

        result = response.json()
        pricing_debug = result.get("pricing_debug", {})

        assert pricing_debug.get("pricing_mode") == "override", \
            f"Expected pricing_mode='override', got '{pricing_debug.get('pricing_mode')}'"


class TestPricingDebugDeterminism:
    """Tests for pricing_debug determinism."""

    def test_price_hash_deterministic(self):
        """Verify same request produces same price_hash."""
        request = create_validate_request()

        response1 = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)
        response2 = requests.post(f"{BASE_URL}/validate/sizing", json=request, timeout=120)

        assert response1.status_code == 200
        assert response2.status_code == 200

        hash1 = response1.json().get("pricing_debug", {}).get("price_hash")
        hash2 = response2.json().get("pricing_debug", {}).get("price_hash")

        assert hash1 == hash2, f"Price hash not deterministic: {hash1} != {hash2}"

    def test_different_prices_different_hash(self):
        """Verify different prices produce different hash."""
        request1 = create_validate_request()
        request2 = create_validate_request()
        request2["request"]["prices"]["import_price_pln_mwh"] = 1200.0  # Different price

        response1 = requests.post(f"{BASE_URL}/validate/sizing", json=request1, timeout=120)
        response2 = requests.post(f"{BASE_URL}/validate/sizing", json=request2, timeout=120)

        assert response1.status_code == 200
        assert response2.status_code == 200

        hash1 = response1.json().get("pricing_debug", {}).get("price_hash")
        hash2 = response2.json().get("pricing_debug", {}).get("price_hash")

        assert hash1 != hash2, "Different prices should produce different hash"
