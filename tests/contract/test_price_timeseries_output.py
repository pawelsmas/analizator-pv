"""
Contract tests for PriceTimeseries output (v2.0.0).

Tests verify:
- Without flag: price_timeseries absent
- With flag: price_timeseries present with correct length
- price_hash is deterministic (same request = same hash)
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_sizing_request(n_hours: int = 24, include_price_timeseries: bool = False):
    """Create a basic sizing request."""
    return {
        "pv_generation_kw": [50.0] * n_hours,
        "load_kw": [30.0] * n_hours,
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_kwh": 0.8,
            "export_price_pln_kwh": 0.4,
        },
        "include_price_timeseries": include_price_timeseries,
    }


class TestPriceTimeseriesOutput:
    """Contract tests for price_timeseries output."""

    def test_price_timeseries_absent_without_flag(self):
        """Verify price_timeseries is absent when flag is false."""
        request = create_sizing_request(include_price_timeseries=False)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        variants = result.get("variants", [])
        assert len(variants) > 0, "No variants in response"

        # Check recommended variant
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        assert "price_timeseries" not in recommended or recommended.get("price_timeseries") is None, \
            "price_timeseries should be absent without flag"
        assert "price_hash" not in recommended or recommended.get("price_hash") is None, \
            "price_hash should be absent without flag"

    def test_price_timeseries_present_with_flag(self):
        """Verify price_timeseries is present when flag is true."""
        request = create_sizing_request(include_price_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), None)
        assert recommended is not None, "No recommended variant"

        price_ts = recommended.get("price_timeseries")
        assert price_ts is not None, "price_timeseries should be present with flag"

        # Verify structure
        assert "import_price_pln_per_mwh" in price_ts
        assert "export_price_pln_per_mwh" in price_ts
        assert "steps" in price_ts
        assert "step_minutes" in price_ts

    def test_price_timeseries_length_matches_steps(self):
        """Verify price array length matches period_info.steps."""
        n_hours = 48
        request = create_sizing_request(n_hours=n_hours, include_price_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        price_ts = recommended.get("price_timeseries")

        assert price_ts is not None
        assert len(price_ts["import_price_pln_per_mwh"]) == n_hours, \
            f"Expected {n_hours} import prices, got {len(price_ts['import_price_pln_per_mwh'])}"
        assert len(price_ts["export_price_pln_per_mwh"]) == n_hours, \
            f"Expected {n_hours} export prices, got {len(price_ts['export_price_pln_per_mwh'])}"
        assert price_ts["steps"] == n_hours

    def test_price_hash_is_present(self):
        """Verify price_hash is present when flag is true."""
        request = create_sizing_request(include_price_timeseries=True)
        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)

        assert response.status_code == 200, f"Sizing failed: {response.text}"
        result = response.json()

        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)

        price_hash = recommended.get("price_hash")
        assert price_hash is not None, "price_hash should be present with flag"
        assert len(price_hash) == 64, f"price_hash should be 64 chars, got {len(price_hash)}"

    def test_price_hash_is_deterministic(self):
        """Verify same request produces same price_hash."""
        request = create_sizing_request(include_price_timeseries=True)

        # First request
        response1 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response1.status_code == 200
        result1 = response1.json()
        recommended1 = next((v for v in result1.get("variants", []) if v.get("is_recommended")), None)
        hash1 = recommended1.get("price_hash")

        # Second request (identical)
        response2 = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response2.status_code == 200
        result2 = response2.json()
        recommended2 = next((v for v in result2.get("variants", []) if v.get("is_recommended")), None)
        hash2 = recommended2.get("price_hash")

        assert hash1 == hash2, f"Hash not deterministic: {hash1} != {hash2}"

    def test_different_prices_different_hash(self):
        """Verify different prices produce different hash."""
        request1 = create_sizing_request(include_price_timeseries=True)
        request2 = create_sizing_request(include_price_timeseries=True)
        request2["prices"]["import_price_pln_kwh"] = 1.0  # Different price

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

        assert hash1 != hash2, "Different prices should produce different hash"

    def test_price_values_are_plausible(self):
        """Verify price values are in expected range (PLN/MWh)."""
        request = create_sizing_request(include_price_timeseries=True)
        request["prices"]["import_price_pln_kwh"] = 0.8  # 800 PLN/MWh
        request["prices"]["export_price_pln_kwh"] = 0.4  # 400 PLN/MWh

        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response.status_code == 200

        result = response.json()
        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        price_ts = recommended.get("price_timeseries")

        # Check values are converted to PLN/MWh
        import_prices = price_ts["import_price_pln_per_mwh"]
        export_prices = price_ts["export_price_pln_per_mwh"]

        # Should be around 800 PLN/MWh for import (0.8 * 1000)
        assert all(p == 800.0 for p in import_prices), \
            f"Expected 800 PLN/MWh, got {import_prices[0]}"

        # Should be around 400 PLN/MWh for export (0.4 * 1000)
        assert all(p == 400.0 for p in export_prices), \
            f"Expected 400 PLN/MWh, got {export_prices[0]}"

    def test_15min_resolution(self):
        """Verify 15-minute resolution produces 4x more steps."""
        n_hours = 24
        n_steps_15min = n_hours * 4

        request = {
            "pv_generation_kw": [50.0] * n_steps_15min,
            "load_kw": [30.0] * n_steps_15min,
            "interval_minutes": 15,
            "battery_power_kw": 50.0,
            "battery_energy_kwh": 100.0,
            "mode": "pv_surplus",
            "prices": {
                "import_price_pln_kwh": 0.8,
                "export_price_pln_kwh": 0.4,
            },
            "include_price_timeseries": True,
        }

        response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
        assert response.status_code == 200, f"Sizing failed: {response.text}"

        result = response.json()
        recommended = next((v for v in result.get("variants", []) if v.get("is_recommended")), None)
        price_ts = recommended.get("price_timeseries")

        assert price_ts["step_minutes"] == 15
        assert price_ts["steps"] == n_steps_15min
        assert len(price_ts["import_price_pln_per_mwh"]) == n_steps_15min
