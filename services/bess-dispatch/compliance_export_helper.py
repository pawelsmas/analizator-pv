"""
Compliance Export Helper - SSoT for compliance export logic (v4.3.0 PR6).

Provides:
- ExportExtractor - extract data for compliance export
- RedactionRules - configurable field redaction
- ManifestBuilder - create export manifest with SHA256 hashes
- export_to_bundle() - create complete export ZIP bundle

Usage:
    from compliance_export_helper import (
        ExportExtractor,
        RedactionRules,
        ManifestBuilder,
        export_to_bundle,
    )

    extractor = ExportExtractor(stores)
    data = extractor.extract(tenant_id, options)

    rules = RedactionRules.default()
    redacted = rules.apply(data)

    manifest = ManifestBuilder.build(files)
"""

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field


class ExportDataType(Enum):
    """Types of data that can be exported."""
    RUNS = "runs"
    JOBS = "jobs"
    AUDIT_LOGS = "audit_logs"
    RETENTION_POLICIES = "retention_policies"
    LEGAL_HOLDS = "legal_holds"
    PURGE_RUNS = "purge_runs"
    USERS = "users"
    API_KEYS = "api_keys"


class RedactionMode(Enum):
    """Redaction modes."""
    NONE = "none"           # No redaction
    STANDARD = "standard"   # Standard PII redaction
    STRICT = "strict"       # Strict redaction (more fields)


# Default fields to redact per data type
DEFAULT_REDACTION_FIELDS: Dict[str, Set[str]] = {
    "users": {"password_hash", "mfa_secret", "mfa_backup_codes"},
    "api_keys": {"key_hash", "key_prefix"},
    "audit_logs": {"ip_address", "user_agent"},
    "runs": set(),
    "jobs": set(),
}

# Additional fields for strict mode
STRICT_REDACTION_FIELDS: Dict[str, Set[str]] = {
    "users": {"email", "phone"},
    "audit_logs": {"details"},
}


class RedactionRules(BaseModel):
    """Configuration for data redaction."""

    mode: RedactionMode = Field(default=RedactionMode.STANDARD)
    fields_by_type: Dict[str, Set[str]] = Field(default_factory=dict)
    redaction_value: str = Field(default="[REDACTED]")
    hash_pii: bool = Field(
        default=False,
        description="Hash PII instead of replacing with placeholder",
    )

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def default(cls) -> "RedactionRules":
        """Create default redaction rules."""
        return cls(
            mode=RedactionMode.STANDARD,
            fields_by_type=DEFAULT_REDACTION_FIELDS.copy(),
        )

    @classmethod
    def strict(cls) -> "RedactionRules":
        """Create strict redaction rules."""
        fields = {}
        for dtype, default_fields in DEFAULT_REDACTION_FIELDS.items():
            fields[dtype] = default_fields.copy()
            if dtype in STRICT_REDACTION_FIELDS:
                fields[dtype].update(STRICT_REDACTION_FIELDS[dtype])
        return cls(
            mode=RedactionMode.STRICT,
            fields_by_type=fields,
        )

    @classmethod
    def none(cls) -> "RedactionRules":
        """Create no-redaction rules."""
        return cls(
            mode=RedactionMode.NONE,
            fields_by_type={},
        )

    def should_redact(self, data_type: str, field_name: str) -> bool:
        """Check if a field should be redacted."""
        if self.mode == RedactionMode.NONE:
            return False
        fields = self.fields_by_type.get(data_type, set())
        return field_name in fields

    def redact_value(self, value: Any, field_name: str) -> str:
        """Redact a value."""
        if self.hash_pii and value:
            # Hash the value for correlation without exposing PII
            return f"SHA256:{hashlib.sha256(str(value).encode()).hexdigest()[:16]}"
        return self.redaction_value

    def apply_to_record(
        self,
        record: Dict[str, Any],
        data_type: str,
    ) -> Dict[str, Any]:
        """Apply redaction to a single record."""
        if self.mode == RedactionMode.NONE:
            return record

        result = {}
        for key, value in record.items():
            if self.should_redact(data_type, key):
                result[key] = self.redact_value(value, key)
            elif isinstance(value, dict):
                result[key] = self.apply_to_record(value, data_type)
            elif isinstance(value, list):
                result[key] = [
                    self.apply_to_record(item, data_type)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def apply_to_list(
        self,
        records: List[Dict[str, Any]],
        data_type: str,
    ) -> List[Dict[str, Any]]:
        """Apply redaction to a list of records."""
        return [self.apply_to_record(r, data_type) for r in records]


class ExportOptions(BaseModel):
    """Options for compliance export."""

    include_runs: bool = Field(default=True)
    include_jobs: bool = Field(default=True)
    include_audit_logs: bool = Field(default=True)
    include_retention_policies: bool = Field(default=True)
    include_legal_holds: bool = Field(default=True)
    include_purge_runs: bool = Field(default=True)
    include_users: bool = Field(default=False)
    include_api_keys: bool = Field(default=False)

    date_from: Optional[str] = Field(
        default=None,
        description="Filter data from this date (ISO format)",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="Filter data to this date (ISO format)",
    )

    redaction_mode: RedactionMode = Field(default=RedactionMode.STANDARD)
    max_records_per_type: int = Field(
        default=100000,
        description="Maximum records per data type",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "include_runs": self.include_runs,
            "include_jobs": self.include_jobs,
            "include_audit_logs": self.include_audit_logs,
            "include_retention_policies": self.include_retention_policies,
            "include_legal_holds": self.include_legal_holds,
            "include_purge_runs": self.include_purge_runs,
            "include_users": self.include_users,
            "include_api_keys": self.include_api_keys,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "redaction_mode": self.redaction_mode.value,
            "max_records_per_type": self.max_records_per_type,
        }


class ExportedData(BaseModel):
    """Container for extracted export data."""

    tenant_id: str
    project_id: Optional[str] = None
    exported_at: str
    options: Dict[str, Any]

    runs: List[Dict[str, Any]] = Field(default_factory=list)
    jobs: List[Dict[str, Any]] = Field(default_factory=list)
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)
    retention_policies: List[Dict[str, Any]] = Field(default_factory=list)
    legal_holds: List[Dict[str, Any]] = Field(default_factory=list)
    purge_runs: List[Dict[str, Any]] = Field(default_factory=list)
    users: List[Dict[str, Any]] = Field(default_factory=list)
    api_keys: List[Dict[str, Any]] = Field(default_factory=list)

    def get_counts(self) -> Dict[str, int]:
        """Get record counts by type."""
        return {
            "runs": len(self.runs),
            "jobs": len(self.jobs),
            "audit_logs": len(self.audit_logs),
            "retention_policies": len(self.retention_policies),
            "legal_holds": len(self.legal_holds),
            "purge_runs": len(self.purge_runs),
            "users": len(self.users),
            "api_keys": len(self.api_keys),
        }

    def total_records(self) -> int:
        """Get total record count."""
        return sum(self.get_counts().values())


class ExportExtractor:
    """
    Extractor for compliance export data.

    Pulls data from various stores based on export options.
    """

    def __init__(
        self,
        compliance_store=None,
        auth_store=None,
        audit_store=None,
        run_store=None,
        job_store=None,
    ):
        """
        Initialize extractor with data stores.

        Args:
            compliance_store: ComplianceStore instance
            auth_store: AuthStore instance (optional)
            audit_store: AuditStore instance (optional)
            run_store: Store for sizing runs (optional)
            job_store: Store for batch jobs (optional)
        """
        self.compliance_store = compliance_store
        self.auth_store = auth_store
        self.audit_store = audit_store
        self.run_store = run_store
        self.job_store = job_store

    def extract(
        self,
        tenant_id: str,
        options: ExportOptions,
        project_id: Optional[str] = None,
    ) -> ExportedData:
        """
        Extract data for compliance export.

        Args:
            tenant_id: Tenant ID
            options: Export options
            project_id: Optional project scope

        Returns:
            ExportedData with extracted records
        """
        data = ExportedData(
            tenant_id=tenant_id,
            project_id=project_id,
            exported_at=datetime.now(timezone.utc).isoformat(),
            options=options.to_dict(),
        )

        # Extract from compliance store
        if self.compliance_store:
            if options.include_retention_policies:
                data.retention_policies = self._extract_retention_policies(
                    tenant_id, project_id, options
                )
            if options.include_legal_holds:
                data.legal_holds = self._extract_legal_holds(
                    tenant_id, project_id, options
                )
            if options.include_purge_runs:
                data.purge_runs = self._extract_purge_runs(
                    tenant_id, project_id, options
                )

        # Extract from auth store
        if self.auth_store:
            if options.include_users:
                data.users = self._extract_users(tenant_id, options)
            if options.include_api_keys:
                data.api_keys = self._extract_api_keys(tenant_id, options)

        # Extract from audit store
        if self.audit_store and options.include_audit_logs:
            data.audit_logs = self._extract_audit_logs(tenant_id, options)

        # Extract runs and jobs (mock for now - would connect to actual stores)
        if options.include_runs:
            data.runs = self._extract_runs(tenant_id, project_id, options)
        if options.include_jobs:
            data.jobs = self._extract_jobs(tenant_id, project_id, options)

        return data

    def _extract_retention_policies(
        self,
        tenant_id: str,
        project_id: Optional[str],
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract retention policies."""
        policies = []

        # Get tenant policy
        tenant_policy = self.compliance_store.get_retention_policy(
            tenant_id, project_id=None
        )
        if tenant_policy:
            policies.append(tenant_policy)

        # Get project policy if scoped
        if project_id:
            project_policy = self.compliance_store.get_retention_policy(
                tenant_id, project_id=project_id
            )
            if project_policy:
                policies.append(project_policy)

        return policies[:options.max_records_per_type]

    def _extract_legal_holds(
        self,
        tenant_id: str,
        project_id: Optional[str],
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract legal holds."""
        holds = self.compliance_store.list_legal_holds(
            tenant_id=tenant_id,
            project_id=project_id,
            active_only=False,
        )
        return holds[:options.max_records_per_type]

    def _extract_purge_runs(
        self,
        tenant_id: str,
        project_id: Optional[str],
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract purge runs."""
        runs = self.compliance_store.list_purge_runs(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=options.max_records_per_type,
        )
        return runs

    def _extract_users(
        self,
        tenant_id: str,
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract users."""
        if not self.auth_store:
            return []
        try:
            users = self.auth_store.list_users(tenant_id)
            return users[:options.max_records_per_type]
        except Exception:
            return []

    def _extract_api_keys(
        self,
        tenant_id: str,
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract API keys."""
        if not self.auth_store:
            return []
        try:
            keys = self.auth_store.list_api_keys(tenant_id)
            return keys[:options.max_records_per_type]
        except Exception:
            return []

    def _extract_audit_logs(
        self,
        tenant_id: str,
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract audit logs."""
        if not self.audit_store:
            return []
        try:
            logs = self.audit_store.list_events(
                tenant_id=tenant_id,
                limit=options.max_records_per_type,
            )
            return logs
        except Exception:
            return []

    def _extract_runs(
        self,
        tenant_id: str,
        project_id: Optional[str],
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract sizing runs."""
        if not self.run_store:
            return []
        try:
            runs = self.run_store.list_runs(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=options.max_records_per_type,
            )
            return runs
        except Exception:
            return []

    def _extract_jobs(
        self,
        tenant_id: str,
        project_id: Optional[str],
        options: ExportOptions,
    ) -> List[Dict[str, Any]]:
        """Extract batch jobs."""
        if not self.job_store:
            return []
        try:
            jobs = self.job_store.list_jobs(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=options.max_records_per_type,
            )
            return jobs
        except Exception:
            return []


class FileEntry(BaseModel):
    """Entry in export manifest."""

    filename: str
    size_bytes: int
    sha256: str
    record_count: Optional[int] = None
    data_type: Optional[str] = None


class ExportManifest(BaseModel):
    """Manifest for compliance export bundle."""

    version: str = Field(default="1.0")
    created_at: str
    tenant_id: str
    project_id: Optional[str] = None

    export_options: Dict[str, Any]
    redaction_mode: str

    files: List[FileEntry] = Field(default_factory=list)
    total_records: int = Field(default=0)
    total_size_bytes: int = Field(default=0)

    checksums: Dict[str, str] = Field(
        default_factory=dict,
        description="SHA256 checksums by filename",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "export_options": self.export_options,
            "redaction_mode": self.redaction_mode,
            "files": [f.model_dump() for f in self.files],
            "total_records": self.total_records,
            "total_size_bytes": self.total_size_bytes,
            "checksums": self.checksums,
        }


class ManifestBuilder:
    """Builder for export manifests."""

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Compute SHA256 hash of data."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def build(
        tenant_id: str,
        files: Dict[str, bytes],
        options: ExportOptions,
        project_id: Optional[str] = None,
        record_counts: Optional[Dict[str, int]] = None,
    ) -> ExportManifest:
        """
        Build manifest for export files.

        Args:
            tenant_id: Tenant ID
            files: Dictionary of filename -> file contents
            options: Export options used
            project_id: Optional project scope
            record_counts: Optional record counts by data type

        Returns:
            ExportManifest with checksums
        """
        record_counts = record_counts or {}

        manifest = ExportManifest(
            created_at=datetime.now(timezone.utc).isoformat(),
            tenant_id=tenant_id,
            project_id=project_id,
            export_options=options.to_dict(),
            redaction_mode=options.redaction_mode.value,
        )

        for filename, content in files.items():
            sha256 = ManifestBuilder.compute_sha256(content)
            data_type = filename.replace(".json", "").replace("data_", "")

            entry = FileEntry(
                filename=filename,
                size_bytes=len(content),
                sha256=sha256,
                record_count=record_counts.get(data_type),
                data_type=data_type if data_type in record_counts else None,
            )
            manifest.files.append(entry)
            manifest.checksums[filename] = sha256
            manifest.total_size_bytes += len(content)

        manifest.total_records = sum(record_counts.values())
        return manifest


def export_to_bundle(
    tenant_id: str,
    options: ExportOptions,
    extractor: ExportExtractor,
    project_id: Optional[str] = None,
) -> bytes:
    """
    Create complete compliance export ZIP bundle.

    Args:
        tenant_id: Tenant ID
        options: Export options
        extractor: ExportExtractor instance
        project_id: Optional project scope

    Returns:
        ZIP file contents as bytes
    """
    # Extract data
    data = extractor.extract(tenant_id, options, project_id)

    # Apply redaction
    if options.redaction_mode == RedactionMode.STRICT:
        rules = RedactionRules.strict()
    elif options.redaction_mode == RedactionMode.NONE:
        rules = RedactionRules.none()
    else:
        rules = RedactionRules.default()

    # Prepare files
    files: Dict[str, bytes] = {}
    record_counts: Dict[str, int] = {}

    def add_data_file(name: str, records: List[Dict[str, Any]], data_type: str):
        if records:
            redacted = rules.apply_to_list(records, data_type)
            content = json.dumps(redacted, indent=2, default=str).encode("utf-8")
            files[f"data_{name}.json"] = content
            record_counts[name] = len(records)

    add_data_file("runs", data.runs, "runs")
    add_data_file("jobs", data.jobs, "jobs")
    add_data_file("audit_logs", data.audit_logs, "audit_logs")
    add_data_file("retention_policies", data.retention_policies, "retention_policies")
    add_data_file("legal_holds", data.legal_holds, "legal_holds")
    add_data_file("purge_runs", data.purge_runs, "purge_runs")
    add_data_file("users", data.users, "users")
    add_data_file("api_keys", data.api_keys, "api_keys")

    # Add metadata
    metadata = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "exported_at": data.exported_at,
        "options": data.options,
        "record_counts": data.get_counts(),
        "total_records": data.total_records(),
    }
    files["metadata.json"] = json.dumps(metadata, indent=2).encode("utf-8")

    # Build manifest
    manifest = ManifestBuilder.build(
        tenant_id=tenant_id,
        files=files,
        options=options,
        project_id=project_id,
        record_counts=record_counts,
    )
    files["manifest.json"] = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")

    # Create ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)

    return zip_buffer.getvalue()


def verify_bundle_integrity(bundle_bytes: bytes) -> Dict[str, Any]:
    """
    Verify integrity of an export bundle.

    Args:
        bundle_bytes: ZIP file contents

    Returns:
        Dictionary with verification results
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "files_checked": 0,
        "checksums_valid": 0,
    }

    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            # Read manifest
            if "manifest.json" not in zf.namelist():
                result["valid"] = False
                result["errors"].append("Missing manifest.json")
                return result

            manifest_data = json.loads(zf.read("manifest.json"))
            checksums = manifest_data.get("checksums", {})

            # Verify each file
            for filename in zf.namelist():
                if filename == "manifest.json":
                    continue

                result["files_checked"] += 1
                content = zf.read(filename)
                computed_hash = ManifestBuilder.compute_sha256(content)

                if filename in checksums:
                    if computed_hash == checksums[filename]:
                        result["checksums_valid"] += 1
                    else:
                        result["valid"] = False
                        result["errors"].append(
                            f"Checksum mismatch for {filename}"
                        )
                else:
                    result["warnings"].append(
                        f"No checksum found for {filename}"
                    )

    except zipfile.BadZipFile:
        result["valid"] = False
        result["errors"].append("Invalid ZIP file")
    except json.JSONDecodeError:
        result["valid"] = False
        result["errors"].append("Invalid manifest JSON")
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Verification error: {str(e)}")

    return result
