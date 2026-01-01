"""
Unit tests for default compat=clean behavior (v2.8.0 PR1).

Tests verify:
- parse_compat_mode returns CLEAN when param is None
- parse_compat_mode returns CLEAN for invalid values
- apply_compat_mode removes deprecated fields in CLEAN mode
"""

import pytest
import sys
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestParseCompatModeDefault:
    """Tests for parse_compat_mode default behavior."""

    def test_none_returns_clean(self):
        """None should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode

        result = parse_compat_mode(None)
        assert result == CompatMode.CLEAN

    def test_empty_string_returns_clean(self):
        """Empty string should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode

        result = parse_compat_mode("")
        assert result == CompatMode.CLEAN

    def test_invalid_value_returns_clean(self):
        """Invalid value should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode

        result = parse_compat_mode("invalid")
        assert result == CompatMode.CLEAN

    def test_clean_returns_clean(self):
        """'clean' should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode

        result = parse_compat_mode("clean")
        assert result == CompatMode.CLEAN

    def test_legacy_returns_legacy(self):
        """'legacy' should return LEGACY mode."""
        from compat_mode import parse_compat_mode, CompatMode

        result = parse_compat_mode("legacy")
        assert result == CompatMode.LEGACY

    def test_case_insensitive(self):
        """Mode parsing should be case insensitive."""
        from compat_mode import parse_compat_mode, CompatMode

        assert parse_compat_mode("CLEAN") == CompatMode.CLEAN
        assert parse_compat_mode("LEGACY") == CompatMode.LEGACY
        assert parse_compat_mode("Clean") == CompatMode.CLEAN
        assert parse_compat_mode("Legacy") == CompatMode.LEGACY


class TestApplyCompatModeClean:
    """Tests for apply_compat_mode in CLEAN mode."""

    def test_clean_removes_export_revenue_pln(self):
        """CLEAN mode should remove export_revenue_pln."""
        from compat_mode import apply_compat_mode, CompatMode

        response = {
            "export_revenue_pln": 1000,
            "export_savings_pln": 1000,
            "other_field": "value",
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert "export_revenue_pln" not in result
        assert "export_savings_pln" in result
        assert "other_field" in result

    def test_clean_removes_nested_deprecated(self):
        """CLEAN mode should remove nested deprecated fields."""
        from compat_mode import apply_compat_mode, CompatMode

        response = {
            "variants": [
                {
                    "export_revenue_pln": 500,
                    "export_savings_pln": 500,
                    "name": "variant1",
                }
            ],
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert "export_revenue_pln" not in result["variants"][0]
        assert "export_savings_pln" in result["variants"][0]

    def test_clean_preserves_non_deprecated(self):
        """CLEAN mode should preserve non-deprecated fields."""
        from compat_mode import apply_compat_mode, CompatMode

        response = {
            "npv_pln": 50000,
            "payback_years": 5.5,
            "capex_pln": 100000,
            "variants": [{"name": "S"}, {"name": "M"}],
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert result["npv_pln"] == 50000
        assert result["capex_pln"] == 100000
        assert len(result["variants"]) == 2


class TestApplyCompatModeLegacy:
    """Tests for apply_compat_mode in LEGACY mode."""

    def test_legacy_adds_aliases(self):
        """LEGACY mode should add deprecated field aliases."""
        from compat_mode import apply_compat_mode, CompatMode
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "export_savings_pln": 1000,
            "total_savings_pln": 5000,
        }

        result = apply_compat_mode(response, CompatMode.LEGACY)

        # Should have both old and new fields
        assert "export_savings_pln" in result
        assert "export_revenue_pln" in result
        assert result["export_revenue_pln"] == 1000

    def test_legacy_does_not_overwrite_existing(self):
        """LEGACY mode should not overwrite existing deprecated fields."""
        from compat_mode import apply_compat_mode, CompatMode
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 999,  # Already exists
        }

        result = apply_compat_mode(response, CompatMode.LEGACY)

        # Should keep existing value
        assert result["export_revenue_pln"] == 999


class TestDefaultModeIsClean:
    """Tests verifying default mode is always clean."""

    def test_default_mode_is_clean_enum(self):
        """Default mode should be CLEAN enum value."""
        from compat_mode import parse_compat_mode, CompatMode

        default = parse_compat_mode(None)
        assert default == CompatMode.CLEAN
        assert default.value == "clean"

    def test_no_param_same_as_explicit_clean(self):
        """No param should behave same as explicit clean."""
        from compat_mode import parse_compat_mode, apply_compat_mode, CompatMode

        response = {
            "export_revenue_pln": 1000,
            "export_savings_pln": 1000,
        }

        mode_none = parse_compat_mode(None)
        mode_clean = parse_compat_mode("clean")

        result_none = apply_compat_mode(response.copy(), mode_none)
        result_clean = apply_compat_mode(response.copy(), mode_clean)

        # Both should produce identical results
        assert result_none == result_clean
        assert "export_revenue_pln" not in result_none
        assert "export_revenue_pln" not in result_clean


class TestDeprecatedFieldsLoaded:
    """Tests that deprecated fields are loaded from registry."""

    def test_deprecated_fields_set_not_empty(self):
        """Deprecated fields set should not be empty."""
        from compat_mode import get_deprecated_response_fields

        fields = get_deprecated_response_fields()
        assert len(fields) > 0

    def test_export_revenue_pln_is_deprecated(self):
        """export_revenue_pln should be in deprecated fields."""
        from compat_mode import is_field_deprecated

        assert is_field_deprecated("export_revenue_pln") is True

    def test_non_deprecated_field_not_in_set(self):
        """Non-deprecated fields should not be in deprecated set."""
        from compat_mode import is_field_deprecated

        assert is_field_deprecated("npv_pln") is False
        assert is_field_deprecated("capex_pln") is False
