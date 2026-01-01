"""
Unit tests for compat_mode module (v2.7.0 PR2).

Tests verify:
- CompatMode enum values
- parse_compat_mode function
- apply_compat_mode function
- Deprecated field removal/addition
"""

import pytest
import sys
from pathlib import Path

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestCompatModeEnum:
    """Tests for CompatMode enum."""

    def test_clean_value(self):
        """CLEAN should have value 'clean'."""
        from compat_mode import CompatMode
        assert CompatMode.CLEAN.value == "clean"

    def test_legacy_value(self):
        """LEGACY should have value 'legacy'."""
        from compat_mode import CompatMode
        assert CompatMode.LEGACY.value == "legacy"


class TestParseCompatMode:
    """Tests for parse_compat_mode function."""

    def test_parse_none_returns_clean(self):
        """None should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode(None) == CompatMode.CLEAN

    def test_parse_clean_string(self):
        """'clean' should return CLEAN mode."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("clean") == CompatMode.CLEAN

    def test_parse_legacy_string(self):
        """'legacy' should return LEGACY mode."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("legacy") == CompatMode.LEGACY

    def test_parse_uppercase_clean(self):
        """'CLEAN' should return CLEAN mode (case insensitive)."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("CLEAN") == CompatMode.CLEAN

    def test_parse_uppercase_legacy(self):
        """'LEGACY' should return LEGACY mode (case insensitive)."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("LEGACY") == CompatMode.LEGACY

    def test_parse_mixed_case(self):
        """Mixed case should work."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("Legacy") == CompatMode.LEGACY
        assert parse_compat_mode("Clean") == CompatMode.CLEAN

    def test_parse_invalid_returns_clean(self):
        """Invalid value should default to CLEAN."""
        from compat_mode import parse_compat_mode, CompatMode
        assert parse_compat_mode("invalid") == CompatMode.CLEAN
        assert parse_compat_mode("foo") == CompatMode.CLEAN
        assert parse_compat_mode("") == CompatMode.CLEAN


class TestApplyCompatModeClean:
    """Tests for apply_compat_mode in clean mode."""

    def test_clean_mode_removes_deprecated_fields(self):
        """Clean mode should remove deprecated fields."""
        from compat_mode import apply_compat_mode, CompatMode, _DEPRECATED_RESPONSE_FIELDS

        # Add a test field to deprecated set
        _DEPRECATED_RESPONSE_FIELDS.add("test_deprecated_field")

        response = {
            "status": "ok",
            "test_deprecated_field": "should be removed",
            "normal_field": "should remain",
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert "test_deprecated_field" not in result
        assert "normal_field" in result
        assert result["normal_field"] == "should remain"

        # Cleanup
        _DEPRECATED_RESPONSE_FIELDS.discard("test_deprecated_field")

    def test_clean_mode_preserves_non_deprecated(self):
        """Clean mode should preserve non-deprecated fields."""
        from compat_mode import apply_compat_mode, CompatMode

        response = {
            "field1": "value1",
            "field2": 123,
            "nested": {"a": 1, "b": 2},
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert result["field1"] == "value1"
        assert result["field2"] == 123
        assert result["nested"]["a"] == 1


class TestApplyCompatModeLegacy:
    """Tests for apply_compat_mode in legacy mode."""

    def test_legacy_mode_adds_aliases(self):
        """Legacy mode should add field aliases."""
        from compat_mode import apply_compat_mode, CompatMode, _FIELD_ALIASES
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        # Assuming export_savings_pln -> export_revenue_pln alias
        response = {
            "export_savings_pln": 1000.0,
        }

        result = apply_compat_mode(response, CompatMode.LEGACY)

        # export_revenue_pln alias should be added from export_savings_pln
        if "export_revenue_pln" in _FIELD_ALIASES:
            source = _FIELD_ALIASES["export_revenue_pln"]
            if source in response:
                assert "export_revenue_pln" in result
                assert result["export_revenue_pln"] == response[source]

    def test_legacy_mode_preserves_existing(self):
        """Legacy mode should preserve existing fields."""
        from compat_mode import apply_compat_mode, CompatMode
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "existing_field": "value",
            "another_field": 42,
        }

        result = apply_compat_mode(response, CompatMode.LEGACY)

        assert result["existing_field"] == "value"
        assert result["another_field"] == 42


class TestNestedDeprecation:
    """Tests for handling nested deprecated fields."""

    def test_clean_removes_nested_deprecated(self):
        """Clean mode should remove deprecated fields in nested objects."""
        from compat_mode import apply_compat_mode, CompatMode, _DEPRECATED_RESPONSE_FIELDS

        _DEPRECATED_RESPONSE_FIELDS.add("nested_deprecated")

        response = {
            "outer": {
                "nested_deprecated": "should be removed",
                "normal": "should remain",
            }
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        assert "nested_deprecated" not in result["outer"]
        assert result["outer"]["normal"] == "should remain"

        _DEPRECATED_RESPONSE_FIELDS.discard("nested_deprecated")

    def test_clean_handles_arrays(self):
        """Clean mode should handle arrays of objects."""
        from compat_mode import apply_compat_mode, CompatMode, _DEPRECATED_RESPONSE_FIELDS

        _DEPRECATED_RESPONSE_FIELDS.add("array_deprecated")

        response = {
            "items": [
                {"array_deprecated": "remove", "keep": 1},
                {"array_deprecated": "remove", "keep": 2},
            ]
        }

        result = apply_compat_mode(response, CompatMode.CLEAN)

        for item in result["items"]:
            assert "array_deprecated" not in item
            assert "keep" in item

        _DEPRECATED_RESPONSE_FIELDS.discard("array_deprecated")


class TestDeprecatedFieldsSet:
    """Tests for deprecated fields management."""

    def test_get_deprecated_response_fields_returns_set(self):
        """get_deprecated_response_fields should return a set."""
        from compat_mode import get_deprecated_response_fields

        result = get_deprecated_response_fields()
        assert isinstance(result, set)

    def test_is_field_deprecated(self):
        """is_field_deprecated should check if field is deprecated."""
        from compat_mode import is_field_deprecated, _DEPRECATED_RESPONSE_FIELDS

        _DEPRECATED_RESPONSE_FIELDS.add("test_deprecated")
        assert is_field_deprecated("test_deprecated") is True
        assert is_field_deprecated("not_deprecated_xyz") is False

        _DEPRECATED_RESPONSE_FIELDS.discard("test_deprecated")


class TestFieldAliases:
    """Tests for field alias configuration."""

    def test_field_aliases_defined(self):
        """_FIELD_ALIASES should be defined."""
        from compat_mode import _FIELD_ALIASES
        assert isinstance(_FIELD_ALIASES, dict)

    def test_export_revenue_alias(self):
        """export_revenue_pln should have alias defined."""
        from compat_mode import _FIELD_ALIASES
        assert "export_revenue_pln" in _FIELD_ALIASES
        assert _FIELD_ALIASES["export_revenue_pln"] == "export_savings_pln"
