"""
Unit tests for contract schema export (v2.6.0 PR1).

Tests verify:
- Schema export is deterministic (same output every time)
- All expected models are exported
- Manifest is correctly generated
- Hash computation is stable
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "scripts/contracts")


class TestExportDeterminism:
    """Tests for deterministic schema export."""

    def test_export_produces_same_output_twice(self):
        """Running export twice should produce identical files."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                path1 = Path(tmpdir1)
                path2 = Path(tmpdir2)

                # Export twice
                results1 = export_schemas(path1)
                results2 = export_schemas(path2)

                # Same number of schemas
                assert len(results1) == len(results2)

                # Compare all files
                for (name1, file1, hash1), (name2, file2, hash2) in zip(results1, results2):
                    assert name1 == name2
                    assert file1 == file2
                    assert hash1 == hash2  # Hashes must be identical

    def test_export_produces_consistent_hashes(self):
        """Hash computation should be stable."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            # Verify each file hash matches computed hash
            for model_name, filename, expected_hash in results:
                filepath = path / filename
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()

                # Recompute hash (strip trailing newline that was added)
                actual_hash = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
                assert actual_hash == expected_hash


class TestExportModels:
    """Tests for model coverage."""

    def test_all_expected_models_exported(self):
        """All models in MODELS_TO_EXPORT should be exported."""
        from export_contracts import export_schemas, MODELS_TO_EXPORT

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            exported_models = {name for name, _, _ in results}
            expected_models = {name for name, _ in MODELS_TO_EXPORT}

            assert exported_models == expected_models

    def test_sizing_models_present(self):
        """Core sizing models should be exported."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            exported_models = {name for name, _, _ in results}

            assert "SizingRequest" in exported_models
            assert "SizingResult" in exported_models

    def test_dispatch_models_present(self):
        """Core dispatch models should be exported."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            exported_models = {name for name, _, _ in results}

            assert "DispatchRequest" in exported_models
            assert "DispatchResult" in exported_models


class TestManifest:
    """Tests for manifest generation."""

    def test_manifest_created(self):
        """Manifest file should be created."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            export_schemas(path)

            manifest_path = path / "manifest.json"
            assert manifest_path.exists()

    def test_manifest_has_version(self):
        """Manifest should include version."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            export_schemas(path)

            with open(path / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)

            assert "version" in manifest
            assert manifest["version"] == "2.6.0"

    def test_manifest_has_schemas_list(self):
        """Manifest should list all schemas."""
        from export_contracts import export_schemas, MODELS_TO_EXPORT

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            export_schemas(path)

            with open(path / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)

            assert "schemas" in manifest
            assert len(manifest["schemas"]) == len(MODELS_TO_EXPORT)

    def test_manifest_schema_entries_have_required_fields(self):
        """Each schema entry should have model, file, hash."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            export_schemas(path)

            with open(path / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)

            for entry in manifest["schemas"]:
                assert "model" in entry
                assert "file" in entry
                assert "hash" in entry


class TestSchemaContent:
    """Tests for schema content."""

    def test_schemas_are_valid_json(self):
        """All schema files should be valid JSON."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            for _, filename, _ in results:
                filepath = path / filename
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                    # Should not raise
                    data = json.loads(content)
                    assert isinstance(data, dict)

    def test_schemas_have_type_field(self):
        """JSON schemas should have a type field (or $defs for complex types)."""
        from export_contracts import export_schemas

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            results = export_schemas(path)

            for _, filename, _ in results:
                filepath = path / filename
                with open(filepath, encoding="utf-8") as f:
                    schema = json.load(f)

                # Skip schemas with errors (model not found)
                if "error" in schema:
                    continue

                # Schema should have type or properties or $defs
                has_structure = (
                    "type" in schema
                    or "properties" in schema
                    or "$defs" in schema
                    or "definitions" in schema
                )
                assert has_structure, f"{filename} missing schema structure"


class TestHashComputation:
    """Tests for hash computation."""

    def test_compute_hash_consistent(self):
        """compute_hash should return same hash for same input."""
        from export_contracts import compute_hash

        content = '{"test": "value"}'
        hash1 = compute_hash(content)
        hash2 = compute_hash(content)

        assert hash1 == hash2

    def test_compute_hash_different_for_different_input(self):
        """compute_hash should return different hash for different input."""
        from export_contracts import compute_hash

        hash1 = compute_hash('{"a": 1}')
        hash2 = compute_hash('{"b": 2}')

        assert hash1 != hash2

    def test_compute_hash_is_sha256(self):
        """compute_hash should use SHA256."""
        from export_contracts import compute_hash

        content = "test"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        actual = compute_hash(content)

        assert actual == expected


class TestSerializeDeterminism:
    """Tests for serialize_schema determinism."""

    def test_serialize_sorts_keys(self):
        """serialize_schema should sort keys."""
        from export_contracts import serialize_schema

        schema = {"z": 1, "a": 2, "m": 3}
        result = serialize_schema(schema)

        # Keys should appear in sorted order
        assert result.index('"a"') < result.index('"m"') < result.index('"z"')

    def test_serialize_uses_indent(self):
        """serialize_schema should use indentation."""
        from export_contracts import serialize_schema

        schema = {"key": "value"}
        result = serialize_schema(schema)

        # Should have newlines (not compact)
        assert "\n" in result
