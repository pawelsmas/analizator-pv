"""
Compliance Export Worker - Background job for compliance exports (v4.3.0 PR7).

Provides:
- ComplianceExportJob model for job tracking
- start_export_job() - initiate async export
- get_export_status() - check job status
- get_export_download() - download completed bundle

Usage:
    from compliance_export_worker import (
        start_export_job,
        get_export_status,
        get_export_download,
    )

    job = start_export_job(store, tenant_id, options, user_id)
    status = get_export_status(store, job.id)
    bundle = get_export_download(store, job.id)
"""

import threading
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from compliance_store import ComplianceStore
from compliance_export_helper import (
    ExportExtractor,
    ExportOptions,
    export_to_bundle,
    verify_bundle_integrity,
)


class ExportJobStatus(Enum):
    """Status of an export job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class ExportJobSummary(BaseModel):
    """Summary of export job for status response."""

    id: str
    tenant_id: str
    project_id: Optional[str] = None
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_by_user_id: str

    # Progress info
    progress_pct: int = Field(default=0)
    current_step: Optional[str] = None

    # Result info
    bundle_size_bytes: Optional[int] = None
    record_count: Optional[int] = None
    error: Optional[str] = None

    # Options used
    options: Dict[str, Any] = Field(default_factory=dict)


class ExportJobResult(BaseModel):
    """Result of completed export job."""

    job_id: str
    tenant_id: str
    project_id: Optional[str] = None
    bundle_bytes: bytes
    bundle_size_bytes: int
    record_count: int
    verification: Dict[str, Any]
    manifest: Dict[str, Any]


# In-memory storage for job bundles (production would use blob storage)
_job_bundles: Dict[str, bytes] = {}
_job_manifests: Dict[str, Dict[str, Any]] = {}
_bundle_lock = threading.Lock()


def _store_bundle(job_id: str, bundle: bytes, manifest: Dict[str, Any]):
    """Store bundle data for download."""
    with _bundle_lock:
        _job_bundles[job_id] = bundle
        _job_manifests[job_id] = manifest


def _get_bundle(job_id: str) -> Optional[bytes]:
    """Get stored bundle data."""
    with _bundle_lock:
        return _job_bundles.get(job_id)


def _get_manifest(job_id: str) -> Optional[Dict[str, Any]]:
    """Get stored manifest."""
    with _bundle_lock:
        return _job_manifests.get(job_id)


def _delete_bundle(job_id: str):
    """Delete stored bundle data."""
    with _bundle_lock:
        _job_bundles.pop(job_id, None)
        _job_manifests.pop(job_id, None)


def start_export_job(
    compliance_store: ComplianceStore,
    tenant_id: str,
    options: ExportOptions,
    created_by_user_id: str,
    project_id: Optional[str] = None,
    extractor: Optional[ExportExtractor] = None,
    run_async: bool = True,
    on_progress: Optional[Callable[[int, str], None]] = None,
) -> ExportJobSummary:
    """
    Start a compliance export job.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        options: Export options
        created_by_user_id: User initiating the export
        project_id: Optional project scope
        extractor: Optional ExportExtractor (created if not provided)
        run_async: Whether to run in background thread
        on_progress: Optional progress callback(pct, step)

    Returns:
        ExportJobSummary with job details
    """
    # Create job record
    job = compliance_store.create_compliance_export(
        tenant_id=tenant_id,
        created_by_user_id=created_by_user_id,
        options=options.to_dict(),
        project_id=project_id,
    )

    job_id = job["id"]

    summary = ExportJobSummary(
        id=job_id,
        tenant_id=tenant_id,
        project_id=project_id,
        status=ExportJobStatus.PENDING.value,
        created_at=job["created_at"],
        created_by_user_id=created_by_user_id,
        options=options.to_dict(),
    )

    if run_async:
        # Run in background thread
        thread = threading.Thread(
            target=_execute_export_job,
            args=(compliance_store, job_id, tenant_id, project_id, options, extractor, on_progress),
            daemon=True,
        )
        thread.start()
    else:
        # Run synchronously
        _execute_export_job(
            compliance_store, job_id, tenant_id, project_id, options, extractor, on_progress
        )

    return summary


def _execute_export_job(
    compliance_store: ComplianceStore,
    job_id: str,
    tenant_id: str,
    project_id: Optional[str],
    options: ExportOptions,
    extractor: Optional[ExportExtractor],
    on_progress: Optional[Callable[[int, str], None]],
):
    """Execute the export job."""
    try:
        # Update status to running
        compliance_store.update_compliance_export(
            export_id=job_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        def progress(pct: int, step: str):
            if on_progress:
                on_progress(pct, step)
            compliance_store.update_compliance_export(
                export_id=job_id,
                progress_pct=pct,
                current_step=step,
            )

        progress(10, "Initializing export")

        # Create extractor if not provided
        if extractor is None:
            extractor = ExportExtractor(compliance_store=compliance_store)

        progress(20, "Extracting data")

        # Create bundle
        bundle = export_to_bundle(
            tenant_id=tenant_id,
            options=options,
            extractor=extractor,
            project_id=project_id,
        )

        progress(70, "Verifying bundle")

        # Verify integrity
        verification = verify_bundle_integrity(bundle)

        if not verification["valid"]:
            raise ValueError(f"Bundle verification failed: {verification['errors']}")

        progress(90, "Storing bundle")

        # Extract manifest from bundle
        import io
        import json
        import zipfile
        with zipfile.ZipFile(io.BytesIO(bundle), "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        # Store bundle for download
        _store_bundle(job_id, bundle, manifest)

        progress(100, "Complete")

        # Update job as completed
        compliance_store.update_compliance_export(
            export_id=job_id,
            status="completed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            bundle_size_bytes=len(bundle),
            record_count=manifest.get("total_records", 0),
            manifest=manifest,
        )

    except Exception as e:
        # Update job as failed
        compliance_store.update_compliance_export(
            export_id=job_id,
            status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=str(e),
            error_detail=traceback.format_exc(),
        )


def get_export_status(
    compliance_store: ComplianceStore,
    job_id: str,
) -> Optional[ExportJobSummary]:
    """
    Get status of an export job.

    Args:
        compliance_store: ComplianceStore instance
        job_id: Job ID

    Returns:
        ExportJobSummary or None if not found
    """
    job = compliance_store.get_compliance_export(job_id)
    if not job:
        return None

    return ExportJobSummary(
        id=job["id"],
        tenant_id=job["tenant_id"],
        project_id=job.get("project_id"),
        status=job["status"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        created_by_user_id=job["created_by_user_id"],
        progress_pct=job.get("progress_pct", 0),
        current_step=job.get("current_step"),
        bundle_size_bytes=job.get("bundle_size_bytes"),
        record_count=job.get("record_count"),
        error=job.get("error"),
        options=job.get("options", {}),
    )


def get_export_download(
    compliance_store: ComplianceStore,
    job_id: str,
) -> Optional[ExportJobResult]:
    """
    Get download data for a completed export job.

    Args:
        compliance_store: ComplianceStore instance
        job_id: Job ID

    Returns:
        ExportJobResult with bundle or None if not found/not ready
    """
    job = compliance_store.get_compliance_export(job_id)
    if not job:
        return None

    if job["status"] != "completed":
        return None

    bundle = _get_bundle(job_id)
    manifest = _get_manifest(job_id)

    if not bundle or not manifest:
        return None

    return ExportJobResult(
        job_id=job_id,
        tenant_id=job["tenant_id"],
        project_id=job.get("project_id"),
        bundle_bytes=bundle,
        bundle_size_bytes=len(bundle),
        record_count=manifest.get("total_records", 0),
        verification={"valid": True},
        manifest=manifest,
    )


def list_export_jobs(
    compliance_store: ComplianceStore,
    tenant_id: str,
    project_id: Optional[str] = None,
    limit: int = 50,
) -> List[ExportJobSummary]:
    """
    List export jobs for a tenant.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        project_id: Optional project filter
        limit: Maximum jobs to return

    Returns:
        List of ExportJobSummary
    """
    jobs = compliance_store.list_compliance_exports(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
    )

    return [
        ExportJobSummary(
            id=job["id"],
            tenant_id=job["tenant_id"],
            project_id=job.get("project_id"),
            status=job["status"],
            created_at=job["created_at"],
            started_at=job.get("started_at"),
            finished_at=job.get("finished_at"),
            created_by_user_id=job["created_by_user_id"],
            progress_pct=job.get("progress_pct", 0),
            current_step=job.get("current_step"),
            bundle_size_bytes=job.get("bundle_size_bytes"),
            record_count=job.get("record_count"),
            error=job.get("error"),
            options=job.get("options", {}),
        )
        for job in jobs
    ]


def delete_export_bundle(
    compliance_store: ComplianceStore,
    job_id: str,
) -> bool:
    """
    Delete an export bundle (cleanup).

    Args:
        compliance_store: ComplianceStore instance
        job_id: Job ID

    Returns:
        True if deleted
    """
    job = compliance_store.get_compliance_export(job_id)
    if not job:
        return False

    _delete_bundle(job_id)

    # Update job status to expired
    compliance_store.update_compliance_export(
        export_id=job_id,
        status="expired",
    )

    return True


def cleanup_expired_bundles(
    compliance_store: ComplianceStore,
    tenant_id: str,
    max_age_hours: int = 24,
) -> int:
    """
    Clean up expired export bundles.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        max_age_hours: Maximum age before cleanup

    Returns:
        Number of bundles cleaned up
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    jobs = compliance_store.list_compliance_exports(tenant_id=tenant_id, limit=1000)

    cleaned = 0
    for job in jobs:
        if job["status"] == "completed":
            finished_at = job.get("finished_at")
            if finished_at:
                try:
                    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                    if finished < cutoff:
                        delete_export_bundle(compliance_store, job["id"])
                        cleaned += 1
                except (ValueError, TypeError):
                    pass

    return cleaned
