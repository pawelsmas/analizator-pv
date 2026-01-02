"""
Unit tests for compliance export helper (v4.3.0 PR6).

Tests:
- RedactionRules: modes, field redaction, hash_pii
- ExportOptions: defaults, serialization
- ExportExtractor: extraction from stores
- ManifestBuilder: SHA256 checksums
- export_to_bundle: ZIP creation
- verify_bundle_integrity: checksum verification
"""

import io
import json
import os
import sys
import tempfile
import zipfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_export_helper import (
    RedactionMode,
    RedactionRules,
    ExportOptions,
    ExportedData,
    ExportExtractor,
    ExportDataType,
    FileEntry,
    ExportManifest,
    ManifestBuilder,
    export_to_bundle,
    verify_bundle_integrity,
    DEFAULT_REDACTION_FIELDS,
    STRICT_REDACTION_FIELDS,
)
from compliance_store import ComplianceStore


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a ComplianceStore with temporary database."""
    return ComplianceStore(db_path=temp_db)


class TestRedactionMode:
    """Tests for RedactionMode enum."""

    def test_redaction_mode_values(self):
        """Test redaction mode enum values."""
        assert RedactionMode.NONE.value == "none"
        assert RedactionMode.STANDARD.value == "standard"
        assert RedactionMode.STRICT.value == "strict"


class TestRedactionRules:
    """Tests for RedactionRules model."""

    def test_default_rules(self):
        """Test default redaction rules."""
        rules = RedactionRules.default()
        assert rules.mode == RedactionMode.STANDARD
        assert "users" in rules.fields_by_type
        assert "password_hash" in rules.fields_by_type["users"]

    def test_strict_rules(self):
        """Test strict redaction rules."""
        rules = RedactionRules.strict()
        assert rules.mode == RedactionMode.STRICT
        # Should include default + strict fields
        assert "password_hash" in rules.fields_by_type["users"]
        assert "email" in rules.fields_by_type["users"]

    def test_none_rules(self):
        """Test no-redaction rules."""
        rules = RedactionRules.none()
        assert rules.mode == RedactionMode.NONE
        assert rules.fields_by_type == {}

    def test_should_redact_standard(self):
        """Test should_redact in standard mode."""
        rules = RedactionRules.default()
        assert rules.should_redact("users", "password_hash") is True
        assert rules.should_redact("users", "name") is False
        assert rules.should_redact("users", "email") is False  # Not in standard

    def test_should_redact_strict(self):
        """Test should_redact in strict mode."""
        rules = RedactionRules.strict()
        assert rules.should_redact("users", "password_hash") is True
        assert rules.should_redact("users", "email") is True
        assert rules.should_redact("users", "name") is False

    def test_should_redact_none_mode(self):
        """Test should_redact in none mode returns False."""
        rules = RedactionRules.none()
        assert rules.should_redact("users", "password_hash") is False
        assert rules.should_redact("users", "email") is False

    def test_redact_value_placeholder(self):
        """Test redact_value returns placeholder."""
        rules = RedactionRules.default()
        assert rules.redact_value("secret123", "password") == "[REDACTED]"

    def test_redact_value_hash_pii(self):
        """Test redact_value with hash_pii=True."""
        rules = RedactionRules(mode=RedactionMode.STANDARD, hash_pii=True)
        result = rules.redact_value("test@example.com", "email")
        assert result.startswith("SHA256:")
        assert len(result) == len("SHA256:") + 16

    def test_redact_value_hash_empty(self):
        """Test redact_value with hash_pii for empty value."""
        rules = RedactionRules(mode=RedactionMode.STANDARD, hash_pii=True)
        result = rules.redact_value("", "email")
        assert result == "[REDACTED]"  # Empty string returns placeholder

    def test_apply_to_record_redacts_fields(self):
        """Test apply_to_record redacts specified fields."""
        rules = RedactionRules.default()
        record = {
            "id": "u1",
            "name": "John",
            "password_hash": "secret123",
            "mfa_secret": "totp-secret",
        }

        result = rules.apply_to_record(record, "users")

        assert result["id"] == "u1"
        assert result["name"] == "John"
        assert result["password_hash"] == "[REDACTED]"
        assert result["mfa_secret"] == "[REDACTED]"

    def test_apply_to_record_nested_dict(self):
        """Test apply_to_record handles nested dicts."""
        rules = RedactionRules.default()
        record = {
            "id": "u1",
            "profile": {
                "name": "John",
                "password_hash": "nested-secret",
            },
        }

        result = rules.apply_to_record(record, "users")

        assert result["profile"]["name"] == "John"
        assert result["profile"]["password_hash"] == "[REDACTED]"

    def test_apply_to_record_list_of_dicts(self):
        """Test apply_to_record handles list of dicts."""
        rules = RedactionRules.default()
        record = {
            "id": "u1",
            "sessions": [
                {"token": "abc", "password_hash": "s1"},
                {"token": "def", "password_hash": "s2"},
            ],
        }

        result = rules.apply_to_record(record, "users")

        assert result["sessions"][0]["token"] == "abc"
        assert result["sessions"][0]["password_hash"] == "[REDACTED]"
        assert result["sessions"][1]["password_hash"] == "[REDACTED]"

    def test_apply_to_record_none_mode(self):
        """Test apply_to_record with none mode returns original."""
        rules = RedactionRules.none()
        record = {"password_hash": "secret123"}

        result = rules.apply_to_record(record, "users")

        assert result["password_hash"] == "secret123"

    def test_apply_to_list(self):
        """Test apply_to_list redacts all records."""
        rules = RedactionRules.default()
        records = [
            {"id": "1", "password_hash": "s1"},
            {"id": "2", "password_hash": "s2"},
        ]

        result = rules.apply_to_list(records, "users")

        assert len(result) == 2
        assert result[0]["password_hash"] == "[REDACTED]"
        assert result[1]["password_hash"] == "[REDACTED]"


class TestExportOptions:
    """Tests for ExportOptions model."""

    def test_default_options(self):
        """Test default export options."""
        opts = ExportOptions()
        assert opts.include_runs is True
        assert opts.include_jobs is True
        assert opts.include_audit_logs is True
        assert opts.include_users is False  # Users not included by default
        assert opts.include_api_keys is False
        assert opts.redaction_mode == RedactionMode.STANDARD
        assert opts.max_records_per_type == 100000

    def test_custom_options(self):
        """Test custom export options."""
        opts = ExportOptions(
            include_runs=False,
            include_users=True,
            redaction_mode=RedactionMode.STRICT,
            max_records_per_type=1000,
        )
        assert opts.include_runs is False
        assert opts.include_users is True
        assert opts.redaction_mode == RedactionMode.STRICT

    def test_date_filters(self):
        """Test date filter options."""
        opts = ExportOptions(
            date_from="2024-01-01T00:00:00Z",
            date_to="2024-12-31T23:59:59Z",
        )
        assert opts.date_from == "2024-01-01T00:00:00Z"
        assert opts.date_to == "2024-12-31T23:59:59Z"

    def test_to_dict(self):
        """Test to_dict serialization."""
        opts = ExportOptions(redaction_mode=RedactionMode.STRICT)
        d = opts.to_dict()

        assert d["include_runs"] is True
        assert d["redaction_mode"] == "strict"
        assert "max_records_per_type" in d


class TestExportedData:
    """Tests for ExportedData model."""

    def test_empty_data(self):
        """Test empty exported data."""
        data = ExportedData(
            tenant_id="t1",
            exported_at="2024-01-01T00:00:00Z",
            options={},
        )
        assert data.runs == []
        assert data.jobs == []
        assert data.total_records() == 0

    def test_get_counts(self):
        """Test get_counts method."""
        data = ExportedData(
            tenant_id="t1",
            exported_at="2024-01-01T00:00:00Z",
            options={},
            runs=[{"id": "r1"}, {"id": "r2"}],
            jobs=[{"id": "j1"}],
        )
        counts = data.get_counts()

        assert counts["runs"] == 2
        assert counts["jobs"] == 1
        assert counts["audit_logs"] == 0

    def test_total_records(self):
        """Test total_records method."""
        data = ExportedData(
            tenant_id="t1",
            exported_at="2024-01-01T00:00:00Z",
            options={},
            runs=[{"id": "r1"}],
            jobs=[{"id": "j1"}, {"id": "j2"}],
            audit_logs=[{"id": "a1"}],
        )
        assert data.total_records() == 4


class TestExportExtractor:
    """Tests for ExportExtractor."""

    def test_extractor_no_stores(self):
        """Test extractor with no stores."""
        extractor = ExportExtractor()
        opts = ExportOptions()

        data = extractor.extract("t1", opts)

        assert data.tenant_id == "t1"
        assert data.runs == []
        assert data.jobs == []

    def test_extractor_with_compliance_store(self, store):
        """Test extractor with compliance store."""
        # Create some data
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Test hold",
            created_by_user_id="admin",
        )

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        data = extractor.extract("t1", opts)

        assert len(data.retention_policies) == 1
        assert len(data.legal_holds) == 1

    def test_extractor_respects_options(self, store):
        """Test extractor respects export options."""
        store.create_retention_policy("t1", {"runs_days": 365})

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions(include_retention_policies=False)

        data = extractor.extract("t1", opts)

        assert data.retention_policies == []

    def test_extractor_project_scope(self, store):
        """Test extractor with project scope."""
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_retention_policy("t1", {"runs_days": 90}, project_id="proj-1")

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        data = extractor.extract("t1", opts, project_id="proj-1")

        assert data.project_id == "proj-1"
        # Should include both tenant and project policies
        assert len(data.retention_policies) == 2


class TestFileEntry:
    """Tests for FileEntry model."""

    def test_file_entry_creation(self):
        """Test creating file entry."""
        entry = FileEntry(
            filename="data_runs.json",
            size_bytes=1024,
            sha256="abc123",
            record_count=10,
            data_type="runs",
        )
        assert entry.filename == "data_runs.json"
        assert entry.size_bytes == 1024


class TestManifestBuilder:
    """Tests for ManifestBuilder."""

    def test_compute_sha256(self):
        """Test SHA256 computation."""
        data = b"test data"
        hash_val = ManifestBuilder.compute_sha256(data)

        assert len(hash_val) == 64  # SHA256 hex is 64 chars
        # Verify consistency
        assert ManifestBuilder.compute_sha256(data) == hash_val

    def test_compute_sha256_different_data(self):
        """Test SHA256 differs for different data."""
        hash1 = ManifestBuilder.compute_sha256(b"data1")
        hash2 = ManifestBuilder.compute_sha256(b"data2")
        assert hash1 != hash2

    def test_build_manifest(self):
        """Test building manifest."""
        files = {
            "data_runs.json": b'[{"id": "r1"}]',
            "data_jobs.json": b'[{"id": "j1"}, {"id": "j2"}]',
        }
        opts = ExportOptions()
        record_counts = {"runs": 1, "jobs": 2}

        manifest = ManifestBuilder.build(
            tenant_id="t1",
            files=files,
            options=opts,
            record_counts=record_counts,
        )

        assert manifest.tenant_id == "t1"
        assert manifest.version == "1.0"
        assert len(manifest.files) == 2
        assert manifest.total_records == 3
        assert manifest.total_size_bytes == len(files["data_runs.json"]) + len(files["data_jobs.json"])

    def test_build_manifest_checksums(self):
        """Test manifest contains correct checksums."""
        content = b'[{"id": "test"}]'
        files = {"data_runs.json": content}
        opts = ExportOptions()

        manifest = ManifestBuilder.build("t1", files, opts)

        expected_hash = ManifestBuilder.compute_sha256(content)
        assert manifest.checksums["data_runs.json"] == expected_hash

    def test_build_manifest_with_project(self):
        """Test manifest with project scope."""
        files = {"data.json": b"{}"}
        opts = ExportOptions()

        manifest = ManifestBuilder.build(
            tenant_id="t1",
            files=files,
            options=opts,
            project_id="proj-1",
        )

        assert manifest.project_id == "proj-1"

    def test_manifest_to_dict(self):
        """Test manifest to_dict serialization."""
        manifest = ExportManifest(
            created_at="2024-01-01T00:00:00Z",
            tenant_id="t1",
            export_options={},
            redaction_mode="standard",
            files=[
                FileEntry(filename="f1.json", size_bytes=100, sha256="abc")
            ],
            total_records=10,
            checksums={"f1.json": "abc"},
        )

        d = manifest.to_dict()

        assert d["tenant_id"] == "t1"
        assert len(d["files"]) == 1
        assert d["checksums"]["f1.json"] == "abc"


class TestExportToBundle:
    """Tests for export_to_bundle function."""

    def test_export_creates_valid_zip(self, store):
        """Test export creates valid ZIP file."""
        store.create_retention_policy("t1", {"runs_days": 365})

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        bundle = export_to_bundle("t1", opts, extractor)

        # Verify it's a valid ZIP
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            assert "manifest.json" in zf.namelist()
            assert "metadata.json" in zf.namelist()

    def test_export_contains_data_files(self, store):
        """Test export contains data files."""
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Test",
            created_by_user_id="admin",
        )

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        bundle = export_to_bundle("t1", opts, extractor)

        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            files = zf.namelist()
            assert "data_retention_policies.json" in files
            assert "data_legal_holds.json" in files

    def test_export_redacts_data(self, store):
        """Test export applies redaction."""
        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions(
            include_users=True,
            redaction_mode=RedactionMode.STANDARD,
        )

        # Would need auth_store with users to fully test
        # Just verify bundle is created
        bundle = export_to_bundle("t1", opts, extractor)
        assert len(bundle) > 0

    def test_export_metadata_content(self, store):
        """Test export metadata content."""
        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        bundle = export_to_bundle("t1", opts, extractor)

        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["tenant_id"] == "t1"
            assert "exported_at" in metadata
            assert "record_counts" in metadata

    def test_export_manifest_content(self, store):
        """Test export manifest content."""
        store.create_retention_policy("t1", {"runs_days": 365})

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()

        bundle = export_to_bundle("t1", opts, extractor)

        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == "1.0"
            assert manifest["tenant_id"] == "t1"
            assert "checksums" in manifest
            assert len(manifest["files"]) > 0


class TestVerifyBundleIntegrity:
    """Tests for verify_bundle_integrity function."""

    def test_verify_valid_bundle(self, store):
        """Test verifying valid bundle passes."""
        store.create_retention_policy("t1", {"runs_days": 365})

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()
        bundle = export_to_bundle("t1", opts, extractor)

        result = verify_bundle_integrity(bundle)

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["checksums_valid"] > 0

    def test_verify_missing_manifest(self):
        """Test verifying bundle without manifest fails."""
        # Create ZIP without manifest
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("data.json", b"{}")

        result = verify_bundle_integrity(zip_buffer.getvalue())

        assert result["valid"] is False
        assert "Missing manifest.json" in result["errors"]

    def test_verify_corrupted_file(self, store):
        """Test verifying bundle with corrupted file fails."""
        store.create_retention_policy("t1", {"runs_days": 365})

        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()
        bundle = export_to_bundle("t1", opts, extractor)

        # Corrupt the bundle by modifying a file
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        # Create new ZIP with modified content
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as src:
            with zipfile.ZipFile(zip_buffer, "w") as dst:
                for item in src.namelist():
                    if item == "metadata.json":
                        # Corrupt the file
                        dst.writestr(item, b"corrupted content")
                    else:
                        dst.writestr(item, src.read(item))

        result = verify_bundle_integrity(zip_buffer.getvalue())

        assert result["valid"] is False
        assert any("Checksum mismatch" in e for e in result["errors"])

    def test_verify_invalid_zip(self):
        """Test verifying invalid ZIP fails."""
        result = verify_bundle_integrity(b"not a zip file")

        assert result["valid"] is False
        assert any("Invalid ZIP" in e for e in result["errors"])

    def test_verify_invalid_manifest_json(self):
        """Test verifying bundle with invalid manifest JSON fails."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("manifest.json", b"invalid json {{{")

        result = verify_bundle_integrity(zip_buffer.getvalue())

        assert result["valid"] is False
        assert any("Invalid manifest JSON" in e for e in result["errors"])

    def test_verify_file_without_checksum_warns(self, store):
        """Test verifying file without checksum adds warning."""
        extractor = ExportExtractor(compliance_store=store)
        opts = ExportOptions()
        bundle = export_to_bundle("t1", opts, extractor)

        # Add extra file not in checksums
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as src:
            with zipfile.ZipFile(zip_buffer, "w") as dst:
                for item in src.namelist():
                    dst.writestr(item, src.read(item))
                dst.writestr("extra_file.txt", b"extra content")

        result = verify_bundle_integrity(zip_buffer.getvalue())

        # Should still be valid but have warning
        assert result["valid"] is True
        assert any("No checksum found" in w for w in result["warnings"])


class TestExportDataType:
    """Tests for ExportDataType enum."""

    def test_data_type_values(self):
        """Test data type enum values."""
        assert ExportDataType.RUNS.value == "runs"
        assert ExportDataType.JOBS.value == "jobs"
        assert ExportDataType.AUDIT_LOGS.value == "audit_logs"
        assert ExportDataType.USERS.value == "users"
        assert ExportDataType.API_KEYS.value == "api_keys"

    def test_all_data_types_exist(self):
        """Test all expected data types exist."""
        types = [t.value for t in ExportDataType]
        assert "runs" in types
        assert "jobs" in types
        assert "audit_logs" in types
        assert "retention_policies" in types
        assert "legal_holds" in types
        assert "purge_runs" in types
