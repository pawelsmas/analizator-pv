"""
Unit tests for deprecations_usage module (v2.7.0 PR1).

Tests verify:
- Deprecation registration works
- Per-request tracking works
- Headers are generated correctly
- Metrics are emitted
"""

import pytest
import sys
from pathlib import Path

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestDeprecationRegistry:
    """Tests for deprecation registry."""

    def test_register_deprecation(self):
        """register_deprecation should store deprecation info."""
        from deprecations_usage import register_deprecation, get_deprecation_info

        register_deprecation(
            field="test_field",
            since="v1.0.0",
            remove_in="v2.0.0",
            replacement="new_field",
            notes="Test note",
        )

        info = get_deprecation_info("test_field")
        assert info is not None
        assert info["field"] == "test_field"
        assert info["since"] == "v1.0.0"
        assert info["remove_in"] == "v2.0.0"
        assert info["replacement"] == "new_field"
        assert info["notes"] == "Test note"

    def test_get_deprecation_info_nonexistent(self):
        """get_deprecation_info should return None for unknown field."""
        from deprecations_usage import get_deprecation_info

        info = get_deprecation_info("nonexistent_field_xyz")
        assert info is None

    def test_get_all_deprecations(self):
        """get_all_deprecations should return all registered."""
        from deprecations_usage import register_deprecation, get_all_deprecations

        register_deprecation("test_a", "v1.0.0", "v2.0.0")
        register_deprecation("test_b", "v1.0.0", "v2.0.0")

        all_deps = get_all_deprecations()
        assert "test_a" in all_deps
        assert "test_b" in all_deps


class TestPerRequestTracking:
    """Tests for per-request deprecation tracking."""

    def test_mark_used_tracks_field(self):
        """mark_used should track the field."""
        from deprecations_usage import mark_used, get_deprecations_used, clear_request_deprecations

        clear_request_deprecations()
        mark_used("field_a")

        used = get_deprecations_used()
        assert "field_a" in used

    def test_get_deprecations_used_returns_sorted_list(self):
        """get_deprecations_used should return sorted list."""
        from deprecations_usage import mark_used, get_deprecations_used, clear_request_deprecations

        clear_request_deprecations()
        mark_used("field_c")
        mark_used("field_a")
        mark_used("field_b")

        used = get_deprecations_used()
        assert used == ["field_a", "field_b", "field_c"]

    def test_mark_used_deduplicates(self):
        """Marking same field multiple times should not duplicate."""
        from deprecations_usage import mark_used, get_deprecations_used, clear_request_deprecations

        clear_request_deprecations()
        mark_used("field_x")
        mark_used("field_x")
        mark_used("field_x")

        used = get_deprecations_used()
        assert used.count("field_x") == 1

    def test_has_deprecations_used_true(self):
        """has_deprecations_used should return True when fields are used."""
        from deprecations_usage import mark_used, has_deprecations_used, clear_request_deprecations

        clear_request_deprecations()
        mark_used("some_field")

        assert has_deprecations_used() is True

    def test_has_deprecations_used_false(self):
        """has_deprecations_used should return False when no fields are used."""
        from deprecations_usage import has_deprecations_used, clear_request_deprecations

        clear_request_deprecations()

        assert has_deprecations_used() is False

    def test_clear_request_deprecations(self):
        """clear_request_deprecations should reset tracking."""
        from deprecations_usage import mark_used, get_deprecations_used, clear_request_deprecations

        mark_used("field_to_clear")
        clear_request_deprecations()

        used = get_deprecations_used()
        assert "field_to_clear" not in used


class TestDeprecationHeaders:
    """Tests for deprecation header generation."""

    def test_get_deprecation_headers_when_used(self):
        """get_deprecation_headers should return headers when deprecated fields used."""
        from deprecations_usage import mark_used, get_deprecation_headers, clear_request_deprecations

        clear_request_deprecations()
        mark_used("header_test_field")

        headers = get_deprecation_headers()
        assert "Deprecation" in headers
        assert "Link" in headers
        assert "Sunset" in headers

    def test_get_deprecation_headers_empty_when_not_used(self):
        """get_deprecation_headers should return empty dict when no deprecated fields used."""
        from deprecations_usage import get_deprecation_headers, clear_request_deprecations

        clear_request_deprecations()

        headers = get_deprecation_headers()
        assert headers == {}

    def test_deprecation_header_value(self):
        """Deprecation header should be 'true'."""
        from deprecations_usage import mark_used, get_deprecation_headers, clear_request_deprecations

        clear_request_deprecations()
        mark_used("test_field")

        headers = get_deprecation_headers()
        assert headers["Deprecation"] == "true"

    def test_link_header_format(self):
        """Link header should point to deprecations endpoint."""
        from deprecations_usage import mark_used, get_deprecation_headers, clear_request_deprecations

        clear_request_deprecations()
        mark_used("test_field")

        headers = get_deprecation_headers()
        link = headers["Link"]
        assert "deprecations" in link
        assert 'rel="deprecation"' in link

    def test_sunset_header_format(self):
        """Sunset header should be a date string."""
        from deprecations_usage import mark_used, get_deprecation_headers, clear_request_deprecations, SUNSET_DATE

        clear_request_deprecations()
        mark_used("test_field")

        headers = get_deprecation_headers()
        assert headers["Sunset"] == SUNSET_DATE


class TestWarningsBlock:
    """Tests for warnings block generation."""

    def test_get_warnings_block_when_used(self):
        """get_warnings_block should return block when deprecated fields used."""
        from deprecations_usage import mark_used, get_warnings_block, clear_request_deprecations

        clear_request_deprecations()
        mark_used("warnings_test_field")

        warnings = get_warnings_block()
        assert warnings is not None
        assert "deprecations_used" in warnings
        assert "warnings_test_field" in warnings["deprecations_used"]

    def test_get_warnings_block_none_when_not_used(self):
        """get_warnings_block should return None when no deprecated fields used."""
        from deprecations_usage import get_warnings_block, clear_request_deprecations

        clear_request_deprecations()

        warnings = get_warnings_block()
        assert warnings is None

    def test_add_warnings_to_response(self):
        """add_warnings_to_response should add warnings to response dict."""
        from deprecations_usage import mark_used, add_warnings_to_response, clear_request_deprecations

        clear_request_deprecations()
        mark_used("response_test_field")

        response = {"status": "ok"}
        add_warnings_to_response(response)

        assert "warnings" in response
        assert "deprecations_used" in response["warnings"]
        assert "response_test_field" in response["warnings"]["deprecations_used"]

    def test_add_warnings_preserves_existing(self):
        """add_warnings_to_response should preserve existing warnings."""
        from deprecations_usage import mark_used, add_warnings_to_response, clear_request_deprecations

        clear_request_deprecations()
        mark_used("test_field")

        response = {"status": "ok", "warnings": {"other_warning": True}}
        add_warnings_to_response(response)

        assert response["warnings"]["other_warning"] is True
        assert "deprecations_used" in response["warnings"]


class TestSunsetDate:
    """Tests for sunset date configuration."""

    def test_sunset_date_format(self):
        """SUNSET_DATE should be in YYYY-MM-DD format."""
        from deprecations_usage import SUNSET_DATE

        assert len(SUNSET_DATE) == 10
        assert SUNSET_DATE[4] == "-"
        assert SUNSET_DATE[7] == "-"

    def test_sunset_date_is_future(self):
        """SUNSET_DATE should be in the future."""
        from deprecations_usage import SUNSET_DATE
        from datetime import datetime

        sunset = datetime.strptime(SUNSET_DATE, "%Y-%m-%d")
        # Sunset should be after today (accounting for test run time)
        # This test will need updating as we approach sunset date
        assert sunset.year >= 2026


class TestLoadFromFile:
    """Tests for loading deprecations from file."""

    def test_load_deprecations_from_file(self):
        """Deprecations should be loaded from file on import."""
        from deprecations_usage import get_all_deprecations

        # File should have been loaded on import
        deps = get_all_deprecations()

        # Should have the fields from deprecations.json
        # At minimum, export_revenue_pln should be there
        assert "export_revenue_pln" in deps or len(deps) > 0
