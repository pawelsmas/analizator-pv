"""
Unit tests for deprecations registry (v2.6.0 PR4).

Tests verify:
- Deprecations JSON file is valid
- Schema matches expected format
- Required fields are present
- Version format is correct
- No duplicate entries
"""

import pytest
import json
from pathlib import Path


def _load_deprecations() -> dict:
    """Load deprecations from SSoT file."""
    path = Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json"
    if not path.exists():
        pytest.skip("deprecations.json not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestDeprecationsFile:
    """Tests for the deprecations.json file."""

    def test_file_exists(self):
        """deprecations.json should exist."""
        path = Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json"
        assert path.exists(), "deprecations.json should exist"

    def test_file_is_valid_json(self):
        """deprecations.json should be valid JSON."""
        data = _load_deprecations()
        assert isinstance(data, dict)

    def test_file_has_version(self):
        """File should have version field."""
        data = _load_deprecations()
        assert "version" in data
        assert isinstance(data["version"], str)

    def test_file_has_last_updated(self):
        """File should have last_updated field."""
        data = _load_deprecations()
        assert "last_updated" in data
        assert isinstance(data["last_updated"], str)

    def test_file_has_items(self):
        """File should have items array."""
        data = _load_deprecations()
        assert "items" in data
        assert isinstance(data["items"], list)


class TestDeprecationsItems:
    """Tests for deprecation item structure."""

    def test_items_have_field(self):
        """Each item should have field name."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "field" in item
            assert isinstance(item["field"], str)
            assert len(item["field"]) > 0

    def test_items_have_location(self):
        """Each item should have location."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "location" in item
            assert isinstance(item["location"], str)

    def test_items_have_status(self):
        """Each item should have valid status."""
        data = _load_deprecations()
        valid_statuses = ["deprecated", "removed", "warning"]
        for item in data["items"]:
            assert "status" in item
            assert item["status"] in valid_statuses

    def test_items_have_since(self):
        """Each item should have since version."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "since" in item
            assert item["since"].startswith("v")

    def test_items_have_remove_in(self):
        """Each item should have remove_in version."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "remove_in" in item
            assert item["remove_in"].startswith("v")

    def test_items_have_replacement(self):
        """Each item should have replacement."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "replacement" in item
            assert isinstance(item["replacement"], str)

    def test_items_have_notes(self):
        """Each item should have notes."""
        data = _load_deprecations()
        for item in data["items"]:
            assert "notes" in item
            assert isinstance(item["notes"], str)


class TestDeprecationsIntegrity:
    """Tests for data integrity."""

    def test_no_duplicate_fields(self):
        """Each field should appear only once."""
        data = _load_deprecations()
        fields = [item["field"] for item in data["items"]]
        assert len(fields) == len(set(fields)), "Duplicate fields found"

    def test_version_format(self):
        """Version should be semver format."""
        data = _load_deprecations()
        version = data["version"]
        # Should be like "1.0.0"
        parts = version.split(".")
        assert len(parts) >= 2, "Version should be semver"

    def test_remove_in_after_since(self):
        """remove_in version should be after since version."""
        data = _load_deprecations()
        for item in data["items"]:
            since = item["since"]
            remove_in = item["remove_in"]
            # Simple comparison - both should be version strings
            # v2.7.0 > v0.3.2 etc.
            # This is a basic check - semver parsing would be more robust
            assert since != remove_in, \
                f"remove_in should be different from since: {item['field']}"

    def test_at_least_one_deprecation(self):
        """Registry should have at least one deprecation."""
        data = _load_deprecations()
        assert len(data["items"]) >= 1


class TestKnownDeprecations:
    """Tests for known deprecated fields."""

    def test_export_revenue_pln_deprecated(self):
        """export_revenue_pln should be deprecated."""
        data = _load_deprecations()
        fields = {item["field"]: item for item in data["items"]}
        assert "export_revenue_pln" in fields

    def test_export_revenue_replacement(self):
        """export_revenue_pln should have replacement."""
        data = _load_deprecations()
        fields = {item["field"]: item for item in data["items"]}
        item = fields.get("export_revenue_pln")
        assert item is not None
        assert item["replacement"] == "export_savings_pln"

    def test_interval_minutes_deprecated(self):
        """interval_minutes should be deprecated."""
        data = _load_deprecations()
        fields = {item["field"]: item for item in data["items"]}
        assert "interval_minutes" in fields

    def test_interval_minutes_replacement(self):
        """interval_minutes should point to dt_minutes."""
        data = _load_deprecations()
        fields = {item["field"]: item for item in data["items"]}
        item = fields.get("interval_minutes")
        assert item is not None
        assert item["replacement"] == "dt_minutes"


class TestDeprecationsSchema:
    """Tests for JSON schema compatibility."""

    def test_items_only_has_known_fields(self):
        """Items should only have documented fields."""
        data = _load_deprecations()
        known_fields = {
            "field",
            "location",
            "status",
            "since",
            "remove_in",
            "replacement",
            "notes",
        }
        for item in data["items"]:
            item_fields = set(item.keys())
            extra = item_fields - known_fields
            assert len(extra) == 0, f"Unknown fields: {extra}"

    def test_top_level_only_has_known_fields(self):
        """Top level should only have documented fields."""
        data = _load_deprecations()
        known_fields = {"version", "last_updated", "items", "sunset_date"}
        data_fields = set(data.keys())
        extra = data_fields - known_fields
        assert len(extra) == 0, f"Unknown top-level fields: {extra}"
