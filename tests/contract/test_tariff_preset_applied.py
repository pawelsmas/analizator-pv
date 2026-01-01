"""
Contract tests for tariff_preset field in /pricing/preview (v2.1.0 PR2).

Tests verify:
- pricing_mode == 'preset' when tariff_preset is used
- import_price has constant value for flat preset (510 for pl_flat_2026)
- Preset not found returns 404
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_preset_request(preset_id: str, n_hours: int = 24):
    """Create a /pricing/preview request using tariff_preset."""
    return {
        "interval_minutes": 60,
        "timezone": "Europe/Warsaw",
        "period_start": "2025-01-01T00:00:00",
        "period_end": f"2025-01-01T{n_hours-1:02d}:00:00",
        "tariff_preset": preset_id,
    }


class TestTariffPresetApplied:
    """Tests for tariff_preset in /pricing/preview."""

    def test_pricing_mode_is_preset(self):
        """Verify pricing_mode is 'preset' when tariff_preset used."""
        request = create_preset_request("pl_flat_2026")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200, f"Request failed: {response.text}"
        result = response.json()

        assert result["pricing_mode"] == "preset", \
            f"Expected pricing_mode='preset', got '{result['pricing_mode']}'"

    def test_pl_flat_2026_import_price_is_510(self):
        """Verify pl_flat_2026 has import_price = 510 PLN/MWh."""
        request = create_preset_request("pl_flat_2026")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # All values should be 510 for flat preset
        assert all(p == 510.0 for p in import_prices), \
            f"Import prices should all be 510.0, got {import_prices[:5]}..."

    def test_pl_flat_2026_export_price_is_0(self):
        """Verify pl_flat_2026 has export_price = 0 PLN/MWh."""
        request = create_preset_request("pl_flat_2026")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        export_prices = result["price_timeseries"]["export_price_pln_per_mwh"]

        # All values should be 0 for flat preset
        assert all(p == 0.0 for p in export_prices), \
            f"Export prices should all be 0.0, got {export_prices[:5]}..."

    def test_pl_flat_2026_other_fees_is_451(self):
        """Verify pl_flat_2026 has other_fees = 451 PLN/MWh."""
        request = create_preset_request("pl_flat_2026")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        other_fees = result["price_timeseries"]["other_fees_pln_per_mwh"]

        # All values should be 451 for flat preset
        assert all(p == 451.0 for p in other_fees), \
            f"Other fees should all be 451.0, got {other_fees[:5]}..."

    def test_preset_not_found_returns_404(self):
        """Verify unknown preset returns 404."""
        request = create_preset_request("nonexistent_preset")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 404

    def test_preset_price_hash_deterministic(self):
        """Verify same preset produces same price_hash."""
        request = create_preset_request("pl_flat_2026")

        response1 = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        response2 = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        hash1 = response1.json()["price_hash"]
        hash2 = response2.json()["price_hash"]

        assert hash1 == hash2, f"Price hash not deterministic: {hash1} != {hash2}"


class TestTariffPresetToU:
    """Tests for ToU (time-of-use) tariff presets."""

    def test_tou_preset_has_varying_prices(self):
        """Verify ToU preset has different prices for peak/offpeak."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-06T00:00:00",  # Monday
            "period_end": "2025-01-06T23:00:00",
            "tariff_preset": "pl_tou_simple_2026",
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Should have both peak and off-peak prices (700 and 350 for pl_tou_simple_2026)
        unique_prices = set(import_prices)
        assert len(unique_prices) >= 2, \
            f"ToU preset should have varying prices, got {unique_prices}"

    def test_tou_preset_peak_hours(self):
        """Verify ToU preset has higher prices during peak hours (7-22)."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-06T00:00:00",  # Monday
            "period_end": "2025-01-06T23:00:00",
            "tariff_preset": "pl_tou_simple_2026",
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Peak hours (7-21 in 0-indexed) should have higher price than off-peak
        peak_price = import_prices[10]  # Hour 10 - peak
        offpeak_price = import_prices[2]  # Hour 2 - off-peak

        assert peak_price > offpeak_price, \
            f"Peak price ({peak_price}) should be higher than off-peak ({offpeak_price})"

    def test_tou_preset_weekend_offpeak(self):
        """Verify ToU preset has off-peak prices on weekend."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-04T00:00:00",  # Saturday
            "period_end": "2025-01-04T23:00:00",
            "tariff_preset": "pl_tou_simple_2026",
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Weekend should have consistent off-peak prices (350 for pl_tou_simple_2026)
        unique_prices = set(import_prices)
        assert len(unique_prices) == 1, \
            f"Weekend should have constant price, got {unique_prices}"
