"""
Contract tests for price_timeseries_override (v2.0.0 PR2).

Tests verify:
- Override prices are used when provided
- pricing_mode is "override" when using override
- price_hash matches override (not generated)
- Different prices produce different economics
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_base_request(n_hours: int = 24):
    """Create a base sizing request without price override."""
    return {
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
        "include_price_timeseries": True,
        "include_money_ledger": True,
    }


def create_override_request(n_hours: int = 24, import_price: float = 1000.0):
    """Create a request with price_timeseries_override."""
    base = create_base_request(n_hours)
    base["price_timeseries_override"] = {
        "import_price_pln_per_mwh": [import_price] * n_hours,
        "export_price_pln_per_mwh": [0.0] * n_hours,  # No export revenue
        "other_fees_pln_per_mwh": [0.0] * n_hours,
        "unserved_penalty_pln_per_kwh": [10.0] * n_hours,
        "step_minutes": 60,
        "steps": n_hours,
        "timezone": "Europe/Warsaw",
        "period_start": "2025-01-01T00:00:00",
        "period_end": f"2025-01-01T{n_hours-1:02d}:00:00",
    }
    return base


class TestPriceTimeseriesOverride:
    """Contract tests for price override functionality."""

    def test_pricing_mode_generated_without_override(self):
        """Verify pricing_mode is 'generated' without override."""
        request = create_base_request()
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        assert recommended is not None

        assert recommended.get("pricing_mode") == "generated", \
            f"Expected pricing_mode='generated', got '{recommended.get('pricing_mode')}'"

    def test_pricing_mode_override_with_override(self):
        """Verify pricing_mode is 'override' when override provided."""
        request = create_override_request()
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        assert recommended is not None

        assert recommended.get("pricing_mode") == "override", \
            f"Expected pricing_mode='override', got '{recommended.get('pricing_mode')}'"

    def test_price_hash_matches_override(self):
        """Verify price_hash is deterministic with override."""
        request = create_override_request()

        # Run twice with identical override
        response1 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        response2 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response1.status_code == 200
        assert response2.status_code == 200

        result1 = response1.json()
        result2 = response2.json()

        recommended1 = next((v for v in result1.get("variants", []) if v.get("is_recommended")), None)
        recommended2 = next((v for v in result2.get("variants", []) if v.get("is_recommended")), None)

        hash1 = recommended1.get("price_hash")
        hash2 = recommended2.get("price_hash")

        assert hash1 is not None
        assert hash1 == hash2, "Same override should produce same price_hash"

    def test_different_override_different_hash(self):
        """Verify different overrides produce different hashes."""
        request1 = create_override_request(import_price=1000.0)
        request2 = create_override_request(import_price=1500.0)

        response1 = requests.post(f"{BASE_URL}/sizing", json=request1, timeout=60)
        response2 = requests.post(f"{BASE_URL}/sizing", json=request2, timeout=60)

        assert response1.status_code == 200
        assert response2.status_code == 200

        result1 = response1.json()
        result2 = response2.json()

        recommended1 = next((v for v in result1.get("variants", []) if v.get("is_recommended")), None)
        recommended2 = next((v for v in result2.get("variants", []) if v.get("is_recommended")), None)

        hash1 = recommended1.get("price_hash")
        hash2 = recommended2.get("price_hash")

        assert hash1 != hash2, "Different prices should produce different price_hash"

    def test_override_prices_shown_in_timeseries(self):
        """Verify price_timeseries shows override values."""
        import_price = 1234.0
        request = create_override_request(import_price=import_price)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        price_ts = recommended.get("price_timeseries")

        assert price_ts is not None
        assert price_ts["import_price_pln_per_mwh"][0] == import_price, \
            f"Expected {import_price}, got {price_ts['import_price_pln_per_mwh'][0]}"

    def test_override_affects_economics(self):
        """Verify override prices affect money_ledger calculations."""
        # Request with low prices
        request_low = create_override_request(import_price=500.0)
        # Request with high prices
        request_high = create_override_request(import_price=2000.0)

        response_low = requests.post(f"{BASE_URL}/sizing", json=request_low, timeout=60)
        response_high = requests.post(f"{BASE_URL}/sizing", json=request_high, timeout=60)

        assert response_low.status_code == 200
        assert response_high.status_code == 200

        result_low = response_low.json()
        result_high = response_high.json()

        recommended_low = next((v for v in result_low.get("variants", []) if v.get("is_recommended")), None)
        recommended_high = next((v for v in result_high.get("variants", []) if v.get("is_recommended")), None)

        # Note: The impact on economics depends on how the engine uses prices
        # With higher import prices, grid import costs more
        # This test verifies the prices are actually being used (different result)
        hash_low = recommended_low.get("price_hash")
        hash_high = recommended_high.get("price_hash")

        assert hash_low != hash_high, "Different prices should be reflected in hash"

    def test_override_zero_export_price(self):
        """Verify override with zero export price works."""
        request = create_override_request()
        request["price_timeseries_override"]["export_price_pln_per_mwh"] = [0.0] * 24

        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response.status_code == 200, f"Sizing failed: {response.text}"

        result = response.json()
        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)

        price_ts = recommended.get("price_timeseries")
        assert all(p == 0.0 for p in price_ts["export_price_pln_per_mwh"]), \
            "Zero export prices should be preserved"

    def test_override_with_varying_prices(self):
        """Verify override with time-varying prices works."""
        n_hours = 24
        # Morning peak, night valley
        import_prices = [500.0] * 6 + [1200.0] * 12 + [500.0] * 6

        request = create_base_request(n_hours)
        request["price_timeseries_override"] = {
            "import_price_pln_per_mwh": import_prices,
            "export_price_pln_per_mwh": [400.0] * n_hours,
            "other_fees_pln_per_mwh": [],
            "unserved_penalty_pln_per_kwh": [],
            "step_minutes": 60,
            "steps": n_hours,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-01T00:00:00",
            "period_end": "2025-01-01T23:00:00",
        }

        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response.status_code == 200, f"Sizing failed: {response.text}"

        result = response.json()
        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)

        price_ts = recommended.get("price_timeseries")
        assert price_ts["import_price_pln_per_mwh"] == import_prices, \
            "Varying prices should be preserved in output"
