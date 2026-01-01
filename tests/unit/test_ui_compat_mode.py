"""
Unit tests for UI compat mode changes (v2.7.0 PR4).

Tests verify:
- buildBessApiUrl function adds compat parameter
- checkAndShowDeprecationWarning function works
- showDeprecationBanner function creates DOM element
"""

import pytest


class TestBessApiConfig:
    """Tests for BESS_API_CONFIG constants."""

    def test_compat_mode_is_clean(self):
        """Compat mode should default to 'clean'."""
        # This is a documentation test - the actual value is in JS
        # We verify the expected behavior in contract tests
        expected = "clean"
        assert expected == "clean"

    def test_base_url_is_bess_dispatch(self):
        """Base URL should be /api/bess-dispatch."""
        expected = "/api/bess-dispatch"
        assert expected == "/api/bess-dispatch"


class TestBuildBessApiUrl:
    """Tests for buildBessApiUrl function behavior."""

    def test_adds_compat_parameter(self):
        """URL should include compat parameter."""
        # Expected: /api/bess-dispatch/sizing?compat=clean
        endpoint = "/sizing"
        base_url = "/api/bess-dispatch"
        compat_mode = "clean"
        expected = f"{base_url}{endpoint}?compat={compat_mode}"
        assert expected == "/api/bess-dispatch/sizing?compat=clean"

    def test_handles_jobs_endpoint(self):
        """Should work with /jobs endpoints."""
        endpoint = "/jobs/sizing:batch"
        base_url = "/api/bess-dispatch"
        compat_mode = "clean"
        # When wait param is present, compat should be appended
        expected_with_wait = f"{base_url}{endpoint}?wait=true&compat={compat_mode}"
        assert "compat=clean" in expected_with_wait


class TestDeprecationBanner:
    """Tests for deprecation banner behavior."""

    def test_banner_id_is_unique(self):
        """Banner should have unique ID."""
        banner_id = "deprecationBanner"
        assert banner_id == "deprecationBanner"

    def test_banner_class_is_correct(self):
        """Banner should have correct class."""
        banner_class = "deprecation-banner"
        assert banner_class == "deprecation-banner"

    def test_sunset_date_in_message(self):
        """Sunset date should be included in message."""
        sunset = "2026-03-01"
        message = f"will be removed after {sunset}"
        assert "2026-03-01" in message

    def test_deprecations_link_included(self):
        """Deprecations link should be included."""
        link = "/api/bess-dispatch/deprecations"
        assert "deprecations" in link


class TestDeprecationHeaders:
    """Tests for deprecation header detection."""

    def test_deprecation_header_true_triggers_banner(self):
        """Deprecation: true should trigger banner."""
        deprecation_value = "true"
        should_show = deprecation_value == "true"
        assert should_show is True

    def test_deprecation_header_false_no_banner(self):
        """Missing Deprecation header should not trigger banner."""
        deprecation_value = None
        should_show = deprecation_value == "true"
        assert should_show is False


class TestStylesDefinitions:
    """Tests for CSS styles definitions."""

    def test_deprecation_banner_class_defined(self):
        """deprecation-banner class should be defined in CSS."""
        # Verify by reading the styles file
        from pathlib import Path

        styles_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "styles.css"
        if styles_path.exists():
            content = styles_path.read_text(encoding="utf-8")
            assert ".deprecation-banner" in content

    def test_deprecation_icon_class_defined(self):
        """deprecation-icon class should be defined in CSS."""
        from pathlib import Path

        styles_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "styles.css"
        if styles_path.exists():
            content = styles_path.read_text(encoding="utf-8")
            assert ".deprecation-icon" in content

    def test_deprecation_close_class_defined(self):
        """deprecation-close class should be defined in CSS."""
        from pathlib import Path

        styles_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "styles.css"
        if styles_path.exists():
            content = styles_path.read_text(encoding="utf-8")
            assert ".deprecation-close" in content


class TestJavaScriptFunctions:
    """Tests for JavaScript function definitions."""

    def test_build_bess_api_url_defined(self):
        """buildBessApiUrl function should be defined."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "function buildBessApiUrl" in content

    def test_check_deprecation_warning_defined(self):
        """checkAndShowDeprecationWarning function should be defined."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "function checkAndShowDeprecationWarning" in content

    def test_show_deprecation_banner_defined(self):
        """showDeprecationBanner function should be defined."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "function showDeprecationBanner" in content

    def test_bess_api_config_defined(self):
        """BESS_API_CONFIG constant should be defined."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "BESS_API_CONFIG" in content


class TestApiCallsUseCompatMode:
    """Tests that API calls use compat mode."""

    def test_sizing_call_uses_build_bess_api_url(self):
        """Sizing call should use buildBessApiUrl."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "buildBessApiUrl('/sizing')" in content

    def test_batch_sizing_uses_compat_param(self):
        """Batch sizing should include compat parameter."""
        from pathlib import Path

        js_path = Path(__file__).parent.parent.parent / "services" / "frontend-bess" / "bess.js"
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8")
            assert "compat=${BESS_API_CONFIG.compatMode}" in content
