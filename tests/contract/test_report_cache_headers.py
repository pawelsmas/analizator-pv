"""
Contract tests for report cache X-Cache headers (v2.5.0 PR3).

Tests verify:
- First download returns X-Cache: MISS
- Second download with same params returns X-Cache: HIT
- Different params return X-Cache: MISS
- Headers are present for PDF, XLSX, ZIP formats
"""

import pytest
import requests
from ._api import post_json, DEFAULT_BASE_URL


def _create_sizing_run():
    """Create a sizing run and return run_id."""
    request = {
        "load_kw": [100] * 24,
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }
    resp = post_json("/sizing", request)
    return resp.get("cache_info", {}).get("run_id")


def _get_report(run_id, format="pdf", profile="client", client_name=None):
    """Get a report and return response."""
    url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.{format}"
    params = {"profile": profile}
    if client_name:
        params["client_name"] = client_name
    return requests.get(url, params=params)


class TestPdfCacheHeaders:
    """Tests for PDF report cache headers."""

    def test_first_download_returns_miss(self):
        """First PDF download should return X-Cache: MISS."""
        run_id = _create_sizing_run()
        resp = _get_report(run_id, format="pdf")

        assert resp.status_code == 200
        assert "X-Cache" in resp.headers
        assert resp.headers["X-Cache"] in ("MISS", "DISABLED")

    def test_second_download_returns_hit(self):
        """Second PDF download with same params should return X-Cache: HIT."""
        run_id = _create_sizing_run()

        # First download
        resp1 = _get_report(run_id, format="pdf", profile="client")
        assert resp1.status_code == 200

        # Second download with same params
        resp2 = _get_report(run_id, format="pdf", profile="client")
        assert resp2.status_code == 200
        assert "X-Cache" in resp2.headers
        # Should be HIT if cache is enabled, otherwise DISABLED
        assert resp2.headers["X-Cache"] in ("HIT", "DISABLED")

    def test_different_profile_returns_miss(self):
        """Different profile should return X-Cache: MISS."""
        run_id = _create_sizing_run()

        # First download with client profile
        resp1 = _get_report(run_id, format="pdf", profile="client")
        assert resp1.status_code == 200

        # Second download with engineering profile
        resp2 = _get_report(run_id, format="pdf", profile="engineering")
        assert resp2.status_code == 200
        assert "X-Cache" in resp2.headers
        # Different profile = different cache key = MISS
        assert resp2.headers["X-Cache"] in ("MISS", "DISABLED")

    def test_different_branding_returns_miss(self):
        """Different branding should return X-Cache: MISS."""
        run_id = _create_sizing_run()

        # First download
        resp1 = _get_report(run_id, format="pdf")
        assert resp1.status_code == 200

        # Second download with client_name
        resp2 = _get_report(run_id, format="pdf", client_name="Test Corp")
        assert resp2.status_code == 200
        assert "X-Cache" in resp2.headers
        # Different branding = different cache key = MISS
        assert resp2.headers["X-Cache"] in ("MISS", "DISABLED")


class TestXlsxCacheHeaders:
    """Tests for XLSX report cache headers."""

    def test_first_download_returns_miss(self):
        """First XLSX download should return X-Cache: MISS."""
        run_id = _create_sizing_run()
        resp = _get_report(run_id, format="xlsx")

        assert resp.status_code == 200
        assert "X-Cache" in resp.headers
        assert resp.headers["X-Cache"] in ("MISS", "DISABLED")

    def test_second_download_returns_hit(self):
        """Second XLSX download should return X-Cache: HIT."""
        run_id = _create_sizing_run()

        # First download
        resp1 = _get_report(run_id, format="xlsx")
        assert resp1.status_code == 200

        # Second download
        resp2 = _get_report(run_id, format="xlsx")
        assert resp2.status_code == 200
        assert "X-Cache" in resp2.headers
        assert resp2.headers["X-Cache"] in ("HIT", "DISABLED")


class TestZipCacheHeaders:
    """Tests for ZIP report cache headers."""

    def test_first_download_returns_miss(self):
        """First ZIP download should return X-Cache: MISS."""
        run_id = _create_sizing_run()
        resp = _get_report(run_id, format="zip")

        assert resp.status_code == 200
        assert "X-Cache" in resp.headers
        assert resp.headers["X-Cache"] in ("MISS", "DISABLED")

    def test_second_download_returns_hit(self):
        """Second ZIP download should return X-Cache: HIT."""
        run_id = _create_sizing_run()

        # First download
        resp1 = _get_report(run_id, format="zip")
        assert resp1.status_code == 200

        # Second download
        resp2 = _get_report(run_id, format="zip")
        assert resp2.status_code == 200
        assert "X-Cache" in resp2.headers
        assert resp2.headers["X-Cache"] in ("HIT", "DISABLED")


class TestCrossFormatCache:
    """Tests for cache isolation between formats."""

    def test_pdf_and_xlsx_have_separate_caches(self):
        """PDF and XLSX should have separate cache entries."""
        run_id = _create_sizing_run()

        # Download PDF first
        resp_pdf = _get_report(run_id, format="pdf")
        assert resp_pdf.status_code == 200

        # Download XLSX - should be MISS (separate cache)
        resp_xlsx = _get_report(run_id, format="xlsx")
        assert resp_xlsx.status_code == 200
        assert "X-Cache" in resp_xlsx.headers
        assert resp_xlsx.headers["X-Cache"] in ("MISS", "DISABLED")

        # Download XLSX again - should be HIT
        resp_xlsx2 = _get_report(run_id, format="xlsx")
        assert resp_xlsx2.status_code == 200
        assert resp_xlsx2.headers["X-Cache"] in ("HIT", "DISABLED")


class TestCacheContentIntegrity:
    """Tests for cache content integrity."""

    def test_cached_pdf_matches_original(self):
        """Cached PDF content should match original."""
        run_id = _create_sizing_run()

        # First download
        resp1 = _get_report(run_id, format="pdf")
        content1 = resp1.content

        # Second download (from cache)
        resp2 = _get_report(run_id, format="pdf")
        content2 = resp2.content

        # Content should match
        assert content1 == content2

    def test_cached_content_is_valid_format(self):
        """Cached content should be valid PDF/XLSX/ZIP."""
        run_id = _create_sizing_run()

        # PDF magic bytes
        resp_pdf = _get_report(run_id, format="pdf")
        assert resp_pdf.content[:4] == b"%PDF"

        # XLSX magic bytes (ZIP format)
        resp_xlsx = _get_report(run_id, format="xlsx")
        assert resp_xlsx.content[:2] == b"PK"

        # ZIP magic bytes
        resp_zip = _get_report(run_id, format="zip")
        assert resp_zip.content[:2] == b"PK"
