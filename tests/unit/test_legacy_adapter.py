"""
Unit tests for central legacy adapter (v2.8.0 PR2).

Tests verify:
- apply_legacy_compat adds deprecated field aliases
- Field aliases loaded from deprecations.json
- Recursive field addition in nested structures
- validate_legacy_aliases_consistent detects mismatches
"""

import pytest
import sys
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestApplyLegacyCompat:
    """Tests for apply_legacy_compat function."""

    def test_adds_export_revenue_alias(self):
        """Should add export_revenue_pln alias for export_savings_pln."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {"export_savings_pln": 1000}
        result = apply_legacy_compat(response)

        assert "export_savings_pln" in result
        assert "export_revenue_pln" in result
        assert result["export_revenue_pln"] == 1000

    def test_adds_savings_alias(self):
        """Should add savings_pln alias for total_savings_pln."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {"total_savings_pln": 5000}
        result = apply_legacy_compat(response)

        assert "total_savings_pln" in result
        assert "savings_pln" in result
        assert result["savings_pln"] == 5000

    def test_preserves_existing_values(self):
        """Should preserve original field values."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "export_savings_pln": 1000,
            "npv_pln": 50000,
            "capex_pln": 100000,
        }
        result = apply_legacy_compat(response)

        assert result["export_savings_pln"] == 1000
        assert result["npv_pln"] == 50000
        assert result["capex_pln"] == 100000

    def test_does_not_overwrite_existing_deprecated(self):
        """Should not overwrite if deprecated field already exists."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 999,  # Already exists
        }
        result = apply_legacy_compat(response)

        # Should keep original value
        assert result["export_revenue_pln"] == 999


class TestNestedFieldAddition:
    """Tests for nested field addition."""

    def test_adds_aliases_in_nested_dict(self):
        """Should add aliases in nested dicts."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "variants": [
                {"export_savings_pln": 500, "name": "S"},
                {"export_savings_pln": 1000, "name": "M"},
            ]
        }
        result = apply_legacy_compat(response)

        assert result["variants"][0]["export_revenue_pln"] == 500
        assert result["variants"][1]["export_revenue_pln"] == 1000

    def test_adds_aliases_in_deeply_nested(self):
        """Should add aliases in deeply nested structures."""
        from legacy_adapter import apply_legacy_compat
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        response = {
            "variants": [
                {
                    "name": "S",
                    "economics_breakdown": {
                        "export_savings_pln": 500,
                        "total_savings_pln": 2000,
                    }
                }
            ]
        }
        result = apply_legacy_compat(response)

        breakdown = result["variants"][0]["economics_breakdown"]
        assert breakdown["export_revenue_pln"] == 500
        assert breakdown["savings_pln"] == 2000


class TestGetLegacyFieldAliases:
    """Tests for get_legacy_field_aliases function."""

    def test_returns_dict(self):
        """Should return a dict."""
        from legacy_adapter import get_legacy_field_aliases

        aliases = get_legacy_field_aliases()
        assert isinstance(aliases, dict)

    def test_contains_expected_aliases(self):
        """Should contain expected aliases."""
        from legacy_adapter import get_legacy_field_aliases

        aliases = get_legacy_field_aliases()
        assert "export_revenue_pln" in aliases
        assert aliases["export_revenue_pln"] == "export_savings_pln"

    def test_returns_copy(self):
        """Should return a copy, not the original."""
        from legacy_adapter import get_legacy_field_aliases

        aliases1 = get_legacy_field_aliases()
        aliases1["new_key"] = "value"

        aliases2 = get_legacy_field_aliases()
        assert "new_key" not in aliases2


class TestGetDeprecatedResponseFields:
    """Tests for get_deprecated_response_fields function."""

    def test_returns_set(self):
        """Should return a set."""
        from legacy_adapter import get_deprecated_response_fields

        fields = get_deprecated_response_fields()
        assert isinstance(fields, set)

    def test_not_empty(self):
        """Should not be empty."""
        from legacy_adapter import get_deprecated_response_fields

        fields = get_deprecated_response_fields()
        assert len(fields) > 0

    def test_contains_export_revenue_pln(self):
        """Should contain export_revenue_pln."""
        from legacy_adapter import get_deprecated_response_fields

        fields = get_deprecated_response_fields()
        assert "export_revenue_pln" in fields


class TestIsFieldDeprecated:
    """Tests for is_field_deprecated function."""

    def test_deprecated_field_returns_true(self):
        """Deprecated field should return True."""
        from legacy_adapter import is_field_deprecated

        assert is_field_deprecated("export_revenue_pln") is True

    def test_non_deprecated_field_returns_false(self):
        """Non-deprecated field should return False."""
        from legacy_adapter import is_field_deprecated

        assert is_field_deprecated("npv_pln") is False
        assert is_field_deprecated("capex_pln") is False

    def test_unknown_field_returns_false(self):
        """Unknown field should return False."""
        from legacy_adapter import is_field_deprecated

        assert is_field_deprecated("unknown_field_xyz") is False


class TestAddLegacyWarnings:
    """Tests for add_legacy_warnings function."""

    def test_adds_warnings_key(self):
        """Should add warnings key if missing."""
        from legacy_adapter import add_legacy_warnings

        response = {}
        result = add_legacy_warnings(response)

        assert "warnings" in result
        assert "deprecations_used" in result["warnings"]

    def test_adds_compat_legacy_to_warnings(self):
        """Should add compat=legacy to deprecations_used."""
        from legacy_adapter import add_legacy_warnings

        response = {}
        result = add_legacy_warnings(response)

        assert "compat=legacy" in result["warnings"]["deprecations_used"]

    def test_preserves_existing_warnings(self):
        """Should preserve existing warnings."""
        from legacy_adapter import add_legacy_warnings

        response = {
            "warnings": {
                "deprecations_used": ["some_old_field"],
                "other_warning": "value",
            }
        }
        result = add_legacy_warnings(response)

        assert "some_old_field" in result["warnings"]["deprecations_used"]
        assert "compat=legacy" in result["warnings"]["deprecations_used"]
        assert result["warnings"]["other_warning"] == "value"

    def test_does_not_duplicate(self):
        """Should not duplicate compat=legacy."""
        from legacy_adapter import add_legacy_warnings

        response = {
            "warnings": {
                "deprecations_used": ["compat=legacy"],
            }
        }
        result = add_legacy_warnings(response)

        count = result["warnings"]["deprecations_used"].count("compat=legacy")
        assert count == 1


class TestValidateLegacyAliasesConsistent:
    """Tests for validate_legacy_aliases_consistent function."""

    def test_consistent_returns_empty(self):
        """Consistent aliases should return empty list."""
        from legacy_adapter import validate_legacy_aliases_consistent

        response = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 1000,  # Matches
        }
        inconsistencies = validate_legacy_aliases_consistent(response)

        assert inconsistencies == []

    def test_inconsistent_returns_message(self):
        """Inconsistent aliases should return message."""
        from legacy_adapter import validate_legacy_aliases_consistent

        response = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 999,  # Does not match
        }
        inconsistencies = validate_legacy_aliases_consistent(response)

        assert len(inconsistencies) == 1
        assert "export_revenue_pln" in inconsistencies[0]

    def test_checks_nested(self):
        """Should check nested structures."""
        from legacy_adapter import validate_legacy_aliases_consistent

        response = {
            "variants": [
                {
                    "export_savings_pln": 500,
                    "export_revenue_pln": 501,  # Inconsistent
                }
            ]
        }
        inconsistencies = validate_legacy_aliases_consistent(response)

        assert len(inconsistencies) == 1

    def test_no_aliases_returns_empty(self):
        """No alias fields should return empty list."""
        from legacy_adapter import validate_legacy_aliases_consistent

        response = {
            "npv_pln": 50000,
            "capex_pln": 100000,
        }
        inconsistencies = validate_legacy_aliases_consistent(response)

        assert inconsistencies == []
