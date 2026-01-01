"""
Contract tests for /api/bess-dispatch/pricing/preview endpoint (v2.1.0 PR1).

Tests verify:
- 200 OK response with correct structure
- len(import_price) == period_info.steps
- Deterministic price_hash (same request -> same hash)
- pricing_mode is 'generated' for standard requests
"""

import pytest
import requests

BASE_URL = "http://localhost:8031"


def create_pricing_preview_request(n_hours: int = 24):
    """Create a basic /pricing/preview request."""
    return {
        "interval_minutes": 60,
        "timezone": "Europe/Warsaw",
        "period_start": "2025-01-01T00:00:00",
        "period_end": f"2025-01-01T{n_hours-1:02d}:00:00",
        "pricing_config": {
            "import_price_pln_mwh": 800.0,
            "export_price_pln_mwh": 400.0,
        },
    }


class TestPricingPreviewBasic:
    """Basic tests for /pricing/preview endpoint."""

    def test_pricing_preview_returns_200(self):
        """Verify endpoint returns 200 OK."""
        request = create_pricing_preview_request(24)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_pricing_preview_response_structure(self):
        """Verify response has all required fields."""
        request = create_pricing_preview_request(24)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        # Check top-level fields
        assert "pricing_mode" in result
        assert "price_hash" in result
        assert "price_timeseries" in result
        assert "period_info" in result

    def test_pricing_preview_period_info_fields(self):
        """Verify period_info has all required fields."""
        request = create_pricing_preview_request(24)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        period_info = result["period_info"]
        assert "period_start" in period_info
        assert "period_end" in period_info
        assert "steps" in period_info
        assert "step_minutes" in period_info
        assert "timezone" in period_info
        assert "period_hours" in period_info
        assert "period_days" in period_info


class TestPricingPreviewTimeseries:
    """Tests for price_timeseries in /pricing/preview response."""

    def test_import_price_length_matches_steps(self):
        """Verify len(import_price) == period_info.steps."""
        request = create_pricing_preview_request(24)
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
            f"import_price length {len(import_prices)} != steps {steps}"

    def test_export_price_length_matches_steps(self):
        """Verify len(export_price) == period_info.steps."""
        request = create_pricing_preview_request(48)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        steps = result["period_info"]["steps"]
        export_prices = result["price_timeseries"]["export_price_pln_per_mwh"]

        assert len(export_prices) == steps, \
            f"export_price length {len(export_prices)} != steps {steps}"

    def test_price_values_match_config(self):
        """Verify price values match the pricing_config."""
        request = create_pricing_preview_request(24)
        request["pricing_config"]["import_price_pln_mwh"] = 900.0
        request["pricing_config"]["export_price_pln_mwh"] = 450.0

        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        import_prices = result["price_timeseries"]["import_price_pln_per_mwh"]
        export_prices = result["price_timeseries"]["export_price_pln_per_mwh"]

        # For flat pricing, all values should be the same
        assert all(p == 900.0 for p in import_prices), "Import prices should all be 900.0"
        assert all(p == 450.0 for p in export_prices), "Export prices should all be 450.0"


class TestPricingPreviewDeterminism:
    """Tests for price_hash determinism."""

    def test_same_request_same_hash(self):
        """Verify two identical requests produce the same price_hash."""
        request = create_pricing_preview_request(24)

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

    def test_price_hash_is_64_char_hex(self):
        """Verify price_hash is a valid 64-character hex string."""
        request = create_pricing_preview_request(24)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        price_hash = result["price_hash"]
        assert len(price_hash) == 64, f"Hash length should be 64, got {len(price_hash)}"
        assert all(c in '0123456789abcdef' for c in price_hash), "Hash should be lowercase hex"

    def test_different_prices_different_hash(self):
        """Verify different prices produce different hash."""
        request1 = create_pricing_preview_request(24)
        request2 = create_pricing_preview_request(24)
        request2["pricing_config"]["import_price_pln_mwh"] = 1000.0  # Different price

        response1 = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request1,
            timeout=30,
        )
        response2 = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request2,
            timeout=30,
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        hash1 = response1.json()["price_hash"]
        hash2 = response2.json()["price_hash"]

        assert hash1 != hash2, "Different prices should produce different hash"


class TestPricingPreviewMode:
    """Tests for pricing_mode field."""

    def test_pricing_mode_is_generated(self):
        """Verify pricing_mode is 'generated' for standard requests."""
        request = create_pricing_preview_request(24)
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        assert result["pricing_mode"] == "generated", \
            f"Expected pricing_mode='generated', got '{result['pricing_mode']}'"


class TestPricingPreviewResolutions:
    """Tests for different time resolutions."""

    def test_15_minute_resolution(self):
        """Verify 15-minute resolution produces correct number of steps."""
        request = {
            "interval_minutes": 15,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-01T00:00:00",
            "period_end": "2025-01-01T05:45:00",  # 6 hours = 24 steps at 15-min
            "pricing_config": {
                "import_price_pln_mwh": 800.0,
                "export_price_pln_mwh": 400.0,
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        assert result["period_info"]["step_minutes"] == 15
        # 6 hours at 15-min = 24 steps, + 1 for inclusive endpoint = 25
        assert result["period_info"]["steps"] == 25

    def test_60_minute_resolution(self):
        """Verify 60-minute resolution produces correct number of steps."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-01T00:00:00",
            "period_end": "2025-01-01T23:00:00",  # 24 hours = 24 steps at 60-min
            "pricing_config": {
                "import_price_pln_mwh": 800.0,
                "export_price_pln_mwh": 400.0,
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 200
        result = response.json()

        assert result["period_info"]["step_minutes"] == 60
        assert result["period_info"]["steps"] == 24


class TestPricingPreviewErrors:
    """Tests for error handling."""

    def test_missing_pricing_config(self):
        """Verify 422 for missing pricing_config."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-01T00:00:00",
            "period_end": "2025-01-01T23:00:00",
            # Missing pricing_config
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        assert response.status_code == 422

    def test_invalid_period(self):
        """Verify 400 for end before start."""
        request = {
            "interval_minutes": 60,
            "timezone": "Europe/Warsaw",
            "period_start": "2025-01-02T00:00:00",
            "period_end": "2025-01-01T00:00:00",  # End before start
            "pricing_config": {
                "import_price_pln_mwh": 800.0,
                "export_price_pln_mwh": 400.0,
            },
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/pricing/preview",
            json=request,
            timeout=30,
        )
        # Should return error (400 or similar)
        assert response.status_code in (400, 422)
