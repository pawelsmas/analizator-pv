"""
Contract tests for tariff_schedule holiday override (v2.1.0 PR3).

Tests verify:
- Holiday dates are treated as weekends (use weekend schedule)
- pricing_mode == 'schedule' when tariff_schedule is used
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_schedule_with_holiday(holiday_date: str):
    """Create a schedule request with a holiday override."""
    # Weekday: hour 10 = 1000 PLN/MWh
    # Weekend: hour 10 = 2000 PLN/MWh
    weekday_prices = [500.0] * 24
    weekday_prices[10] = 1000.0  # Hour 10 peak

    weekend_prices = [600.0] * 24
    weekend_prices[10] = 2000.0  # Hour 10 peak (weekend)

    return {
        "interval_minutes": 60,
        "timezone": "Europe/Warsaw",
        "period_start": f"{holiday_date}T09:00:00",
        "period_end": f"{holiday_date}T11:00:00",  # 3 hours (9, 10, 11)
        "tariff_schedule": {
            "weekday_import_price_pln_per_mwh": weekday_prices,
            "weekend_import_price_pln_per_mwh": weekend_prices,
            "weekday_export_price_pln_per_mwh": [0.0] * 24,
            "weekend_export_price_pln_per_mwh": [0.0] * 24,
            "weekday_other_fees_pln_per_mwh": [100.0] * 24,
            "weekend_other_fees_pln_per_mwh": [50.0] * 24,
            "holiday_dates": [holiday_date],
            "timezone": "Europe/Warsaw",
        },
    }


class TestTariffScheduleHolidayOverride:
    """Tests for holiday override in tariff_schedule."""

    def test_pricing_mode_is_schedule(self):
        """Verify pricing_mode is 'schedule' when tariff_schedule used."""
        # Wednesday (not inherently a weekend)
        request = create_schedule_with_holiday("2025-01-08")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200, f"Request failed: {response.text}"
        result = response.json()

        assert result["pricing_mode"] == "schedule", \
            f"Expected pricing_mode='schedule', got '{result['pricing_mode']}'"

    def test_holiday_uses_weekend_schedule(self):
        """Verify holiday date uses weekend schedule (2000 at hour 10)."""
        # 2025-01-08 is Wednesday - set as holiday
        request = create_schedule_with_holiday("2025-01-08")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Hour 10 (second step: index 1) should have weekend price of 2000
        hour_10_price = import_prices[1]
        assert hour_10_price == 2000.0, \
            f"Holiday hour 10 should use weekend price (2000), got {hour_10_price}"

    def test_holiday_uses_weekend_fees(self):
        """Verify holiday date uses weekend other_fees."""
        request = create_schedule_with_holiday("2025-01-08")
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        other_fees = result["price_timeseries"]["other_fees_pln_per_mwh"]

        # Weekend fees are 50, weekday fees are 100
        # Since it's a holiday, should use weekend fees
        assert all(f == 50.0 for f in other_fees), \
            f"Holiday should use weekend other_fees (50), got {other_fees}"

    def test_weekday_without_holiday_uses_weekday_schedule(self):
        """Verify non-holiday weekday uses weekday schedule."""
        # Create request without holiday override
        weekday_prices = [500.0] * 24
        weekday_prices[10] = 1000.0

        weekend_prices = [600.0] * 24
        weekend_prices[10] = 2000.0

        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-08T09:00:00",  # Wednesday
            "period_end": "2025-01-08T11:00:00",
            "tariff_schedule": {
                "weekday_import_price_pln_per_mwh": weekday_prices,
                "weekend_import_price_pln_per_mwh": weekend_prices,
                "weekday_export_price_pln_per_mwh": [0.0] * 24,
                "weekend_export_price_pln_per_mwh": [0.0] * 24,
                "weekday_other_fees_pln_per_mwh": [100.0] * 24,
                "weekend_other_fees_pln_per_mwh": [50.0] * 24,
                "holiday_dates": [],  # No holidays
                "timezone": "Europe/Warsaw",
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Hour 10 should have weekday price of 1000
        hour_10_price = import_prices[1]
        assert hour_10_price == 1000.0, \
            f"Weekday hour 10 should use weekday price (1000), got {hour_10_price}"


class TestTariffScheduleWeekendAutoDetect:
    """Tests for automatic weekend detection."""

    def test_saturday_uses_weekend_schedule(self):
        """Verify Saturday uses weekend schedule automatically."""
        weekday_prices = [500.0] * 24
        weekday_prices[10] = 1000.0

        weekend_prices = [600.0] * 24
        weekend_prices[10] = 2000.0

        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-04T09:00:00",  # Saturday
            "period_end": "2025-01-04T11:00:00",
            "tariff_schedule": {
                "weekday_import_price_pln_per_mwh": weekday_prices,
                "weekend_import_price_pln_per_mwh": weekend_prices,
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
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Saturday should use weekend price
        hour_10_price = import_prices[1]
        assert hour_10_price == 2000.0, \
            f"Saturday hour 10 should use weekend price (2000), got {hour_10_price}"

    def test_sunday_uses_weekend_schedule(self):
        """Verify Sunday uses weekend schedule automatically."""
        weekday_prices = [500.0] * 24
        weekday_prices[12] = 1500.0

        weekend_prices = [600.0] * 24
        weekend_prices[12] = 2500.0

        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-05T11:00:00",  # Sunday
            "period_end": "2025-01-05T13:00:00",
            "tariff_schedule": {
                "weekday_import_price_pln_per_mwh": weekday_prices,
                "weekend_import_price_pln_per_mwh": weekend_prices,
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
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]

        # Sunday hour 12 should use weekend price
        hour_12_price = import_prices[1]
        assert hour_12_price == 2500.0, \
            f"Sunday hour 12 should use weekend price (2500), got {hour_12_price}"
