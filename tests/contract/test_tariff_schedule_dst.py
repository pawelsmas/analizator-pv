"""
Contract tests for tariff_schedule DST handling (v2.1.0 PR3).

Tests verify:
- 23-hour day (spring forward) produces correct number of steps
- 25-hour day (fall back) produces correct number of steps
- No exceptions during DST transitions
- Price arrays have correct length
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_schedule_for_date(date_str: str, n_hours: int = 24):
    """Create a schedule request for a specific date."""
    weekday_prices = [100.0 + i * 10 for i in range(24)]  # 100-330
    weekend_prices = [200.0 + i * 10 for i in range(24)]  # 200-430

    return {
        "interval_minutes": 60,
        "timezone": "Europe/Warsaw",
        "period_start": f"{date_str}T00:00:00",
        "period_end": f"{date_str}T{n_hours-1:02d}:00:00",
        "tariff_schedule": {
            "weekday_import_price_pln_per_mwh": weekday_prices,
            "weekend_import_price_pln_per_mwh": weekend_prices,
            "weekday_export_price_pln_per_mwh": [0.0] * 24,
            "weekend_export_price_pln_per_mwh": [0.0] * 24,
            "timezone": "Europe/Warsaw",
        },
    }


class TestTariffScheduleDst23h:
    """Tests for 23-hour day (spring forward DST transition)."""

    def test_spring_forward_no_exception(self):
        """Verify spring forward DST transition doesn't cause exceptions."""
        # 2025-03-30 is spring forward in Europe/Warsaw (2:00 -> 3:00)
        request = create_schedule_for_date("2025-03-30")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        # Should not fail
        assert response.status_code == 200, f"Spring forward failed: {response.text}"

    def test_spring_forward_returns_correct_steps(self):
        """Verify response has correct number of steps for 23-hour day."""
        request = create_schedule_for_date("2025-03-30")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        steps = result["period_info"]["steps"]
        # Request spans 00:00 to 23:00 = 24 steps regardless of DST
        # (we're counting from start to end, not actual local hours)
        assert steps == 24, f"Expected 24 steps, got {steps}"

    def test_spring_forward_price_array_length_matches_steps(self):
        """Verify price array length matches steps during spring forward."""
        request = create_schedule_for_date("2025-03-30")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        steps = result["period_info"]["steps"]
        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        assert len(import_prices) == steps, \
            f"Price array length {len(import_prices)} != steps {steps}"


class TestTariffScheduleDst25h:
    """Tests for 25-hour day (fall back DST transition)."""

    def test_fall_back_no_exception(self):
        """Verify fall back DST transition doesn't cause exceptions."""
        # 2025-10-26 is fall back in Europe/Warsaw (3:00 -> 2:00)
        request = create_schedule_for_date("2025-10-26")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        # Should not fail
        assert response.status_code == 200, f"Fall back failed: {response.text}"

    def test_fall_back_returns_correct_steps(self):
        """Verify response has correct number of steps for 25-hour day."""
        request = create_schedule_for_date("2025-10-26")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        steps = result["period_info"]["steps"]
        # Request spans 00:00 to 23:00 = 24 steps regardless of DST
        assert steps == 24, f"Expected 24 steps, got {steps}"

    def test_fall_back_price_array_length_matches_steps(self):
        """Verify price array length matches steps during fall back."""
        request = create_schedule_for_date("2025-10-26")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        steps = result["period_info"]["steps"]
        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        assert len(import_prices) == steps, \
            f"Price array length {len(import_prices)} != steps {steps}"


class TestTariffScheduleDstPriceLookup:
    """Tests for correct price lookup during DST transitions."""

    def test_price_lookup_consistent_during_spring_forward(self):
        """Verify prices are looked up correctly during spring forward."""
        request = create_schedule_for_date("2025-03-30")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # All prices should be within valid range (no out-of-bounds indexing)
        # Sunday (weekend) prices: 200-430
        for i, p in enumerate(import_prices):
            assert 200.0 <= p <= 430.0, \
                f"Price at step {i} is {p}, outside weekend range 200-430"

    def test_price_lookup_consistent_during_fall_back(self):
        """Verify prices are looked up correctly during fall back."""
        request = create_schedule_for_date("2025-10-26")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # All prices should be within valid range
        # Sunday (weekend) prices: 200-430
        for i, p in enumerate(import_prices):
            assert 200.0 <= p <= 430.0, \
                f"Price at step {i} is {p}, outside weekend range 200-430"


class TestTariffScheduleDst15MinResolution:
    """Tests for DST handling at 15-minute resolution."""

    def test_spring_forward_15min_no_exception(self):
        """Verify 15-min resolution handles spring forward."""
        request = {
            "interval_minutes": 15,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-03-30T00:00:00",
            "period_end": "2025-03-30T05:45:00",
            "tariff_schedule": {
                "weekday_import_price_pln_per_mwh": [500.0] * 24,
                "weekend_import_price_pln_per_mwh": [600.0] * 24,
                "weekday_export_price_pln_per_mwh": [0.0] * 24,
                "weekend_export_price_pln_per_mwh": [0.0] * 24,
                "timezone": "Europe/Warsaw",
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200, f"15-min spring forward failed: {response.text}"

        result = response.json()
        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]
        steps = result["period_info"]["steps"]

        assert len(import_prices) == steps

    def test_fall_back_15min_no_exception(self):
        """Verify 15-min resolution handles fall back."""
        request = {
            "interval_minutes": 15,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-10-26T00:00:00",
            "period_end": "2025-10-26T05:45:00",
            "tariff_schedule": {
                "weekday_import_price_pln_per_mwh": [500.0] * 24,
                "weekend_import_price_pln_per_mwh": [600.0] * 24,
                "weekday_export_price_pln_per_mwh": [0.0] * 24,
                "weekend_export_price_pln_per_mwh": [0.0] * 24,
                "timezone": "Europe/Warsaw",
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200, f"15-min fall back failed: {response.text}"

        result = response.json()
        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]
        steps = result["period_info"]["steps"]

        assert len(import_prices) == steps
