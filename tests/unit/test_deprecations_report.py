"""
Unit tests for deprecations report tooling (v2.7.0 PR5).

Tests verify:
- Report generation in different formats
- CI check validation
- Days until sunset calculation
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import date, timedelta


# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "deprecations"))


class TestLoadDeprecations:
    """Tests for load_deprecations function."""

    def test_load_from_docs_api(self):
        """Should load from docs/api/deprecations.json."""
        from report import load_deprecations

        data = load_deprecations()
        assert isinstance(data, dict)
        assert "items" in data
        assert "version" in data

    def test_returns_dict(self):
        """Should return a dict."""
        from report import load_deprecations

        data = load_deprecations()
        assert isinstance(data, dict)


class TestDaysUntilSunset:
    """Tests for get_days_until_sunset function."""

    def test_future_date_returns_positive(self):
        """Future date should return positive days."""
        from report import get_days_until_sunset

        # Use a date far in the future
        future_date = (date.today() + timedelta(days=100)).strftime("%Y-%m-%d")
        days = get_days_until_sunset(future_date)
        assert days > 0

    def test_past_date_returns_negative(self):
        """Past date should return negative days."""
        from report import get_days_until_sunset

        past_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
        days = get_days_until_sunset(past_date)
        assert days < 0

    def test_invalid_date_returns_negative(self):
        """Invalid date should return -1."""
        from report import get_days_until_sunset

        days = get_days_until_sunset("invalid-date")
        assert days == -1


class TestFormatStatusIcon:
    """Tests for format_status_icon function."""

    def test_deprecated_icon(self):
        """Deprecated status should return warning icon."""
        from report import format_status_icon

        icon = format_status_icon("deprecated")
        assert icon == "⚠️"

    def test_removed_icon(self):
        """Removed status should return X icon."""
        from report import format_status_icon

        icon = format_status_icon("removed")
        assert icon == "❌"

    def test_warning_icon(self):
        """Warning status should return lightning icon."""
        from report import format_status_icon

        icon = format_status_icon("warning")
        assert icon == "⚡"

    def test_unknown_icon(self):
        """Unknown status should return question icon."""
        from report import format_status_icon

        icon = format_status_icon("unknown_status")
        assert icon == "❓"


class TestTextReport:
    """Tests for text report generation."""

    def test_generates_string(self):
        """Should generate a string."""
        from report import generate_text_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_text_report(data)
        assert isinstance(report, str)

    def test_includes_version(self):
        """Should include registry version."""
        from report import generate_text_report

        data = {
            "version": "2.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_text_report(data)
        assert "2.0.0" in report

    def test_includes_sunset_date(self):
        """Should include sunset date."""
        from report import generate_text_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_text_report(data)
        assert "2026-03-01" in report


class TestMarkdownReport:
    """Tests for markdown report generation."""

    def test_generates_string(self):
        """Should generate a string."""
        from report import generate_markdown_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_markdown_report(data)
        assert isinstance(report, str)

    def test_includes_markdown_heading(self):
        """Should include markdown heading."""
        from report import generate_markdown_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_markdown_report(data)
        assert "# " in report

    def test_includes_table(self):
        """Should include markdown table."""
        from report import generate_markdown_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [
                {
                    "field": "test_field",
                    "location": "response",
                    "status": "deprecated",
                    "since": "v1.0.0",
                    "remove_in": "v2.0.0",
                    "replacement": "new_field",
                }
            ],
        }
        report = generate_markdown_report(data)
        assert "|" in report
        assert "test_field" in report


class TestJsonReport:
    """Tests for JSON report generation."""

    def test_generates_valid_json(self):
        """Should generate valid JSON."""
        from report import generate_json_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_json_report(data)
        parsed = json.loads(report)
        assert isinstance(parsed, dict)

    def test_includes_generated_at(self):
        """Should include generated_at timestamp."""
        from report import generate_json_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_json_report(data)
        parsed = json.loads(report)
        assert "generated_at" in parsed

    def test_includes_days_until_sunset(self):
        """Should include days_until_sunset."""
        from report import generate_json_report

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [],
        }
        report = generate_json_report(data)
        parsed = json.loads(report)
        assert "days_until_sunset" in parsed


class TestCheckDeprecations:
    """Tests for CI check function."""

    def test_valid_data_returns_true(self):
        """Valid data should return True."""
        from report import check_deprecations

        data = {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "sunset_date": "2026-03-01",
            "items": [
                {
                    "field": "test",
                    "location": "response",
                    "status": "deprecated",
                    "since": "v1.0.0",
                    "remove_in": "v2.0.0",
                    "replacement": "new_test",
                    "notes": "",
                }
            ],
        }
        result = check_deprecations(data)
        assert result is True

    def test_missing_version_returns_false(self):
        """Missing version should return False."""
        from report import check_deprecations

        data = {
            "items": [],
        }
        result = check_deprecations(data)
        assert result is False

    def test_invalid_status_returns_false(self):
        """Invalid status should return False."""
        from report import check_deprecations

        data = {
            "version": "1.0.0",
            "items": [
                {
                    "field": "test",
                    "location": "response",
                    "status": "invalid_status",
                    "since": "v1.0.0",
                    "remove_in": "v2.0.0",
                }
            ],
        }
        result = check_deprecations(data)
        assert result is False

    def test_duplicate_fields_returns_false(self):
        """Duplicate fields should return False."""
        from report import check_deprecations

        data = {
            "version": "1.0.0",
            "items": [
                {
                    "field": "duplicate",
                    "location": "response",
                    "status": "deprecated",
                    "since": "v1.0.0",
                    "remove_in": "v2.0.0",
                },
                {
                    "field": "duplicate",
                    "location": "response",
                    "status": "deprecated",
                    "since": "v1.0.0",
                    "remove_in": "v2.0.0",
                },
            ],
        }
        result = check_deprecations(data)
        assert result is False


class TestCiCheck:
    """Tests for CI check script."""

    def test_ci_check_script_exists(self):
        """ci_check.py should exist."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "deprecations" / "ci_check.py"
        assert script_path.exists()

    def test_ci_check_validates_current_file(self):
        """CI check should pass on current deprecations.json."""
        from ci_check import validate_deprecations, find_deprecations_file

        path = find_deprecations_file()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        errors, warnings = validate_deprecations(data)
        assert len(errors) == 0, f"Unexpected errors: {errors}"
