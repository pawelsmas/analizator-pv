"""
Unit tests for version coherence (v2.6.0 PR6).

Tests verify:
- Version string format is valid
- Contract schemas have version info
- Deprecations have version references
- All version references are coherent
"""

import pytest
import json
import re
from pathlib import Path


def _get_project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent.parent


class TestVersionFormat:
    """Tests for version string format."""

    def test_version_string_format(self):
        """Version should be semver format."""
        # Read version from a known location
        # For now, we test the format regex
        pattern = r"^v?\d+\.\d+\.\d+(-rc\d+)?$"
        valid_versions = [
            "v1.0.0",
            "v2.6.0",
            "v2.6.0-rc1",
            "1.0.0",
            "2.6.0-rc2",
        ]
        for v in valid_versions:
            assert re.match(pattern, v), f"Version {v} should match pattern"

    def test_invalid_version_format(self):
        """Invalid versions should not match."""
        pattern = r"^v?\d+\.\d+\.\d+(-rc\d+)?$"
        invalid_versions = [
            "v1.0",
            "version1",
            "1.0.0.0",
            "v1.0.0-beta",
        ]
        for v in invalid_versions:
            assert not re.match(pattern, v), f"Version {v} should not match pattern"


class TestContractSchemaVersions:
    """Tests for contract schema version info."""

    def test_manifest_exists(self):
        """Contract manifest should exist."""
        manifest_path = _get_project_root() / "docs" / "contracts" / "latest" / "manifest.json"
        assert manifest_path.exists(), "manifest.json should exist"

    def test_manifest_has_version(self):
        """Manifest should have version field."""
        manifest_path = _get_project_root() / "docs" / "contracts" / "latest" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("manifest.json not found")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data, "Manifest should have version"

    def test_manifest_has_hashes(self):
        """Manifest should have hashes for each schema."""
        manifest_path = _get_project_root() / "docs" / "contracts" / "latest" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("manifest.json not found")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for schema in data.get("schemas", []):
            assert "hash" in schema, f"Schema {schema.get('file')} missing hash"
            assert len(schema["hash"]) == 64, "Hash should be 64 chars (SHA256)"

    def test_manifest_has_schemas(self):
        """Manifest should list schemas."""
        manifest_path = _get_project_root() / "docs" / "contracts" / "latest" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("manifest.json not found")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "schemas" in data, "Manifest should have schemas list"
        assert len(data["schemas"]) > 0, "Should have at least one schema"


class TestDeprecationsVersions:
    """Tests for deprecations version references."""

    def test_deprecations_has_version(self):
        """Deprecations file should have version."""
        path = _get_project_root() / "docs" / "api" / "deprecations.json"
        if not path.exists():
            pytest.skip("deprecations.json not found")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data, "Should have version"

    def test_deprecations_since_versions_valid(self):
        """All since versions should be valid semver."""
        path = _get_project_root() / "docs" / "api" / "deprecations.json"
        if not path.exists():
            pytest.skip("deprecations.json not found")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        pattern = r"^v\d+\.\d+\.\d+$"
        for item in data.get("items", []):
            since = item.get("since", "")
            assert re.match(pattern, since), f"Invalid since version: {since}"

    def test_deprecations_remove_in_versions_valid(self):
        """All remove_in versions should be valid semver."""
        path = _get_project_root() / "docs" / "api" / "deprecations.json"
        if not path.exists():
            pytest.skip("deprecations.json not found")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        pattern = r"^v\d+\.\d+\.\d+$"
        for item in data.get("items", []):
            remove_in = item.get("remove_in", "")
            assert re.match(pattern, remove_in), f"Invalid remove_in version: {remove_in}"


class TestVersionCoherence:
    """Tests for version coherence across files."""

    def test_deprecations_not_removed_yet(self):
        """No deprecated fields should be past their removal version."""
        path = _get_project_root() / "docs" / "api" / "deprecations.json"
        if not path.exists():
            pytest.skip("deprecations.json not found")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Current version (would normally come from /version endpoint)
        # For now, we just check that remove_in versions are in the future
        current_major = 2
        current_minor = 6

        for item in data.get("items", []):
            remove_in = item.get("remove_in", "")
            # Parse remove_in version
            match = re.match(r"^v(\d+)\.(\d+)\.\d+$", remove_in)
            if match:
                remove_major = int(match.group(1))
                remove_minor = int(match.group(2))
                # Check if removal version is current or future
                assert (remove_major, remove_minor) >= (current_major, current_minor), \
                    f"Field {item['field']} has remove_in {remove_in} which is past current version"


class TestReleaseChecklist:
    """Tests for release checklist document."""

    def test_checklist_exists(self):
        """Release checklist should exist."""
        path = _get_project_root() / "docs" / "release" / "RELEASE_CHECKLIST.md"
        assert path.exists(), "RELEASE_CHECKLIST.md should exist"

    def test_checklist_has_sections(self):
        """Checklist should have key sections."""
        path = _get_project_root() / "docs" / "release" / "RELEASE_CHECKLIST.md"
        if not path.exists():
            pytest.skip("RELEASE_CHECKLIST.md not found")

        content = path.read_text(encoding="utf-8")

        expected_sections = [
            "Pre-Release",
            "Contract Freeze",
            "Scenario Freeze",
            "Deprecations",
            "RC Validation",
            "Release",
            "Version Coherence",
        ]

        for section in expected_sections:
            assert section in content, f"Missing section: {section}"

    def test_checklist_has_version_format(self):
        """Checklist should document version format."""
        path = _get_project_root() / "docs" / "release" / "RELEASE_CHECKLIST.md"
        if not path.exists():
            pytest.skip("RELEASE_CHECKLIST.md not found")

        content = path.read_text(encoding="utf-8")
        assert "Version Format" in content, "Should document version format"


class TestLocalDevDocs:
    """Tests for local development documentation."""

    def test_local_dev_md_exists(self):
        """LOCAL_DEV.md should exist (or skip if not yet merged)."""
        path = _get_project_root() / "docs" / "LOCAL_DEV.md"
        if not path.exists():
            pytest.skip("LOCAL_DEV.md not found (may be in pending PR)")
        assert path.exists()

    def test_local_dev_has_quick_start(self):
        """LOCAL_DEV.md should have quick start section."""
        path = _get_project_root() / "docs" / "LOCAL_DEV.md"
        if not path.exists():
            pytest.skip("LOCAL_DEV.md not found")

        content = path.read_text(encoding="utf-8")
        assert "Quick Start" in content, "Should have Quick Start section"

    def test_local_dev_has_endpoints(self):
        """LOCAL_DEV.md should list endpoints."""
        path = _get_project_root() / "docs" / "LOCAL_DEV.md"
        if not path.exists():
            pytest.skip("LOCAL_DEV.md not found")

        content = path.read_text(encoding="utf-8")
        assert "localhost:8031" in content, "Should list backend endpoint"
