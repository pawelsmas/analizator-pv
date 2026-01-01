"""
Jobs API router for async job management (v3.4.0 PR2).

Endpoints:
- POST /jobs - Enqueue a new job
- GET /jobs - List jobs for current tenant
- GET /jobs/{job_id} - Get job status, progress, and result
- POST /jobs/{job_id}/cancel - Cancel a queued or running job

Job kinds (implemented in PR3):
- sizing_batch: Batch sizing runs
- report_run: Generate report from run
- report_portfolio: Generate portfolio report
- validate_pack: Validate scenario pack
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth_config import AuthContext
from auth_deps import get_auth_context
from db_session import get_db_session
from db_models import JobQueue
from job_artifacts import list_artifacts, get_artifact, ArtifactInfo


router = APIRouter(prefix="/jobs", tags=["jobs"])


# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

VALID_JOB_KINDS = [
    "sizing_batch",
    "report_run",
    "report_portfolio",
    "validate_pack",
]

CANCELLABLE_STATUSES = ["queued", "running"]


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class EnqueueJobRequest(BaseModel):
    """Request to enqueue a new job."""
    kind: str = Field(..., description="Job kind (sizing_batch, report_run, report_portfolio, validate_pack)")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Job-specific payload")
    idempotency_key: Optional[str] = Field(default=None, description="Optional idempotency key to prevent duplicate jobs")


class JobProgressResponse(BaseModel):
    """Job progress information."""
    current: Optional[int] = Field(default=None, description="Current progress value")
    total: Optional[int] = Field(default=None, description="Total progress value")
    message: Optional[str] = Field(default=None, description="Progress message")
    percent: Optional[float] = Field(default=None, description="Progress percentage (0-100)")


class JobErrorResponse(BaseModel):
    """Job error information."""
    code: str = Field(..., description="Error code")
    detail: Optional[str] = Field(default=None, description="Error detail message")


class JobResponse(BaseModel):
    """Response for a single job."""
    job_id: str = Field(..., description="Unique job identifier")
    tenant_id: str = Field(..., description="Tenant ID")
    kind: str = Field(..., description="Job kind")
    status: str = Field(..., description="Job status (queued, running, succeeded, failed, cancelled)")
    created_at: str = Field(..., description="ISO timestamp when job was created")
    started_at: Optional[str] = Field(default=None, description="ISO timestamp when job started")
    finished_at: Optional[str] = Field(default=None, description="ISO timestamp when job finished")
    attempts: int = Field(..., description="Number of execution attempts")
    max_attempts: int = Field(..., description="Maximum retry attempts")
    progress: Optional[JobProgressResponse] = Field(default=None, description="Job progress")
    error: Optional[JobErrorResponse] = Field(default=None, description="Error info if failed")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Job result if succeeded")


class JobListResponse(BaseModel):
    """Response for listing jobs."""
    items: List[JobResponse]
    total: int
    limit: int
    offset: int


class EnqueueJobResponse(BaseModel):
    """Response for enqueue job."""
    job_id: str
    status: str
    created: bool = Field(default=True, description="True if new job created, False if idempotent hit")


class CancelJobResponse(BaseModel):
    """Response for cancel job."""
    job_id: str
    status: str
    cancelled: bool = Field(default=True, description="True if job was cancelled")


# -------------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------------

def _job_to_response(job: JobQueue, include_result: bool = True) -> JobResponse:
    """Convert JobQueue model to response."""
    # Parse progress JSON
    progress = None
    if job.progress_json:
        try:
            prog_data = json.loads(job.progress_json)
            progress = JobProgressResponse(
                current=prog_data.get("current"),
                total=prog_data.get("total"),
                message=prog_data.get("message"),
                percent=prog_data.get("percent"),
            )
        except json.JSONDecodeError:
            pass

    # Parse error info
    error = None
    if job.error_code:
        error = JobErrorResponse(
            code=job.error_code,
            detail=job.error_detail,
        )

    # Parse result JSON
    result = None
    if include_result and job.result_json and job.status == "succeeded":
        try:
            result = json.loads(job.result_json)
        except json.JSONDecodeError:
            pass

    return JobResponse(
        job_id=job.id,
        tenant_id=job.tenant_id,
        kind=job.kind,
        status=job.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        attempts=job.attempts or 0,
        max_attempts=job.max_attempts or 3,
        progress=progress,
        error=error,
        result=result,
    )


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------

@router.post("", response_model=EnqueueJobResponse)
async def enqueue_job(
    request: EnqueueJobRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Enqueue a new job for async processing.

    The job will be picked up by a worker and executed asynchronously.
    Use GET /jobs/{job_id} to poll for status and result.

    Supported job kinds:
    - sizing_batch: Batch sizing runs
    - report_run: Generate report from run
    - report_portfolio: Generate portfolio report
    - validate_pack: Validate scenario pack

    Optional idempotency_key prevents duplicate job creation.
    """
    # Validate job kind
    if request.kind not in VALID_JOB_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job kind: {request.kind}. Valid kinds: {VALID_JOB_KINDS}"
        )

    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        # Check for idempotency hit
        if request.idempotency_key:
            existing = session.query(JobQueue).filter(
                JobQueue.tenant_id == tenant_id,
                JobQueue.kind == request.kind,
            ).filter(
                # Look for idempotency key in payload
                JobQueue.payload_json.contains(f'"idempotency_key": "{request.idempotency_key}"')
            ).first()

            if existing:
                return EnqueueJobResponse(
                    job_id=existing.id,
                    status=existing.status,
                    created=False,
                )

        # Create new job
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Include idempotency key in payload if provided
        payload = request.payload or {}
        if request.idempotency_key:
            payload["idempotency_key"] = request.idempotency_key

        job = JobQueue(
            id=job_id,
            tenant_id=tenant_id,
            kind=request.kind,
            payload_json=json.dumps(payload) if payload else None,
            status="queued",
            created_at=now,
            attempts=0,
            max_attempts=3,
        )

        session.add(job)
        session.commit()

        return EnqueueJobResponse(
            job_id=job_id,
            status="queued",
            created=True,
        )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    auth: AuthContext = Depends(get_auth_context),
    kind: Optional[str] = Query(default=None, description="Filter by job kind"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
):
    """
    List jobs for the current tenant.

    Supports filtering by kind and status, and pagination.
    Jobs are returned in descending order by created_at (newest first).
    """
    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        query = session.query(JobQueue).filter(JobQueue.tenant_id == tenant_id)

        if kind:
            query = query.filter(JobQueue.kind == kind)
        if status:
            query = query.filter(JobQueue.status == status)

        # Get total count
        total = query.count()

        # Get paginated results
        jobs = query.order_by(JobQueue.created_at.desc()).offset(offset).limit(limit).all()

        return JobListResponse(
            items=[_job_to_response(job, include_result=False) for job in jobs],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Get job status, progress, and result.

    Returns full job details including:
    - Current status (queued, running, succeeded, failed, cancelled)
    - Progress information (current/total/percent/message)
    - Error information if failed
    - Result data if succeeded
    """
    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        job = session.query(JobQueue).filter(
            JobQueue.id == job_id,
            JobQueue.tenant_id == tenant_id,
        ).first()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return _job_to_response(job, include_result=True)


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Cancel a queued or running job.

    Only jobs in 'queued' or 'running' status can be cancelled.
    A cancelled job will not be retried.
    """
    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        job = session.query(JobQueue).filter(
            JobQueue.id == job_id,
            JobQueue.tenant_id == tenant_id,
        ).first()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status not in CANCELLABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Job cannot be cancelled in status: {job.status}"
            )

        # Mark as cancelled
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        job.locked_by = None
        job.locked_until = None

        session.commit()

        return CancelJobResponse(
            job_id=job_id,
            status="cancelled",
            cancelled=True,
        )


# -------------------------------------------------------------------------
# Artifacts endpoints
# -------------------------------------------------------------------------

class ArtifactListResponse(BaseModel):
    """Response for listing job artifacts."""
    job_id: str
    artifacts: List[ArtifactInfo]


@router.get("/{job_id}/artifacts", response_model=ArtifactListResponse)
async def list_job_artifacts(
    job_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    List artifacts produced by a job.

    Returns list of artifact names, content types, and sizes.
    Only available for succeeded jobs that produced artifacts.
    """
    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        job = session.query(JobQueue).filter(
            JobQueue.id == job_id,
            JobQueue.tenant_id == tenant_id,
        ).first()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

    # List artifacts from filesystem
    artifacts = list_artifacts(job_id)

    return ArtifactListResponse(
        job_id=job_id,
        artifacts=artifacts,
    )


@router.get("/{job_id}/artifacts/{artifact_name}")
async def download_artifact(
    job_id: str,
    artifact_name: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Download a specific artifact from a job.

    Returns the artifact file with appropriate content type.
    """
    tenant_id = auth.tenant_id or "default"

    with get_db_session() as session:
        job = session.query(JobQueue).filter(
            JobQueue.id == job_id,
            JobQueue.tenant_id == tenant_id,
        ).first()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

    # Get artifact
    result = get_artifact(job_id, artifact_name)

    if not result:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content, content_type = result

    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact_name}"',
        },
    )
