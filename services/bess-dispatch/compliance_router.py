"""
Compliance API router for BESS API (v4.3.0 PR5).

Endpoints:

Retention Policies:
- GET /compliance/retention - Get effective retention policy
- PUT /compliance/retention - Set tenant-level policy
- GET /compliance/retention/projects/{project_id} - Get project policy
- PUT /compliance/retention/projects/{project_id} - Set project policy
- DELETE /compliance/retention/projects/{project_id} - Remove project override

Legal Holds:
- GET /compliance/holds - List legal holds
- POST /compliance/holds - Create legal hold
- GET /compliance/holds/{hold_id} - Get legal hold details
- DELETE /compliance/holds/{hold_id} - Release legal hold

Purge:
- POST /compliance/purge/dry-run - Preview retention purge
- POST /compliance/purge/execute - Execute retention purge
- GET /compliance/purge/history - List purge history
- GET /compliance/purge/{run_id} - Get purge run details

Requires admin role for all operations.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth_config import AuthContext, Role
from auth_deps import require_role
from audit_store import log_audit
from compliance_store import get_compliance_store
from retention_policy_helper import (
    RetentionPolicy,
    ResourceCategory,
    get_effective_policy,
    validate_policy,
    summarize_policy,
)
from legal_hold_helper import (
    LegalHoldMatcher,
    check_resource_held,
    get_hold_summary,
)
from retention_executor import (
    dry_run_retention,
    execute_retention,
    get_purge_status,
    list_purge_history,
)


router = APIRouter(prefix="/compliance", tags=["compliance"])


# -------------------------------------------------------------------------
# Request/Response models - Retention
# -------------------------------------------------------------------------

class RetentionPolicyRequest(BaseModel):
    """Request to set retention policy."""
    runs_days: Optional[int] = Field(
        default=None,
        description="Retention days for runs (0=indefinite, -1=inherit)",
        ge=-1,
    )
    jobs_days: Optional[int] = Field(
        default=None,
        description="Retention days for jobs (0=indefinite, -1=inherit)",
        ge=-1,
    )
    reports_days: Optional[int] = Field(
        default=None,
        description="Retention days for reports (0=indefinite, -1=inherit)",
        ge=-1,
    )
    audit_logs_days: Optional[int] = Field(
        default=None,
        description="Retention days for audit logs (0=indefinite, -1=inherit)",
        ge=-1,
    )
    exports_days: Optional[int] = Field(
        default=None,
        description="Retention days for exports (0=indefinite, -1=inherit)",
        ge=-1,
    )
    enabled: bool = Field(default=True, description="Whether policy is active")


class RetentionPolicyResponse(BaseModel):
    """Response with retention policy details."""
    runs_days: int
    jobs_days: int
    reports_days: int
    audit_logs_days: int
    exports_days: int
    enabled: bool
    is_effective: bool = Field(
        default=True,
        description="True if this is the effective merged policy",
    )
    summary: Dict[str, str] = Field(
        default_factory=dict,
        description="Human-readable summary",
    )


# -------------------------------------------------------------------------
# Request/Response models - Legal Holds
# -------------------------------------------------------------------------

class LegalHoldCreateRequest(BaseModel):
    """Request to create a legal hold."""
    resource_type: str = Field(
        description="Resource type (run/job/project/all)",
        pattern="^(run|job|project|report|all)s?$",
    )
    reason: str = Field(description="Reason for the hold", min_length=1)
    project_id: Optional[str] = Field(
        default=None,
        description="Scope to specific project",
    )
    resource_id: Optional[str] = Field(
        default=None,
        description="Scope to specific resource",
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="Optional expiry datetime (ISO format)",
    )


class LegalHoldResponse(BaseModel):
    """Response with legal hold details."""
    id: str
    tenant_id: str
    project_id: Optional[str] = None
    resource_type: str
    resource_id: Optional[str] = None
    reason: str
    created_by_user_id: str
    created_at: str
    expires_at: Optional[str] = None
    released_at: Optional[str] = None
    is_active: bool = Field(default=True)


class LegalHoldListResponse(BaseModel):
    """Response for listing legal holds."""
    items: List[LegalHoldResponse]
    total: int
    active_count: int


class HoldSummaryResponse(BaseModel):
    """Summary of holds for tenant."""
    active_count: int
    total_count: int
    by_scope: Dict[str, int]
    by_type: Dict[str, int]


# -------------------------------------------------------------------------
# Request/Response models - Purge
# -------------------------------------------------------------------------

class PurgeDryRunRequest(BaseModel):
    """Request for purge dry run."""
    project_id: Optional[str] = Field(
        default=None,
        description="Scope to specific project",
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description="Specific categories to process (default: all)",
    )


class PurgeExecuteRequest(BaseModel):
    """Request to execute purge."""
    project_id: Optional[str] = Field(
        default=None,
        description="Scope to specific project",
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description="Specific categories to process (default: all)",
    )
    max_deletions: Optional[int] = Field(
        default=None,
        description="Maximum resources to delete",
        ge=1,
        le=10000,
    )


class PurgeCategoryStats(BaseModel):
    """Stats for a single category in purge."""
    category: str
    retention_days: int
    total_found: int
    to_delete: int
    deleted: int
    skipped_held: int
    skipped_error: int


class PurgeResultResponse(BaseModel):
    """Response with purge result."""
    mode: str
    tenant_id: str
    project_id: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    success: bool
    error: Optional[str] = None
    total_found: int
    total_to_delete: int
    total_deleted: int
    total_skipped_held: int
    total_skipped_error: int
    hit_limit: bool
    categories: List[PurgeCategoryStats]


class PurgeHistoryResponse(BaseModel):
    """Response for purge history."""
    items: List[Dict[str, Any]]
    total: int


# -------------------------------------------------------------------------
# Retention Policy Endpoints
# -------------------------------------------------------------------------

@router.get("/retention", response_model=RetentionPolicyResponse)
def get_retention_policy(
    project_id: Optional[str] = Query(
        default=None,
        description="Get effective policy for this project",
    ),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get effective retention policy.

    Returns the merged effective policy (tenant default + project override).
    """
    store = get_compliance_store()
    effective = get_effective_policy(auth.tenant_id, project_id, store)

    return RetentionPolicyResponse(
        runs_days=effective.runs_days or 0,
        jobs_days=effective.jobs_days or 0,
        reports_days=effective.reports_days or 0,
        audit_logs_days=effective.audit_logs_days or 0,
        exports_days=effective.exports_days or 0,
        enabled=True,
        is_effective=True,
        summary=summarize_policy(effective),
    )


@router.put("/retention", response_model=RetentionPolicyResponse)
def set_tenant_retention_policy(
    request: RetentionPolicyRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Set tenant-level retention policy.

    This is the default policy for all projects without overrides.
    """
    store = get_compliance_store()

    policy_json = {
        "runs_days": request.runs_days,
        "jobs_days": request.jobs_days,
        "reports_days": request.reports_days,
        "audit_logs_days": request.audit_logs_days,
        "exports_days": request.exports_days,
    }
    # Remove None values
    policy_json = {k: v for k, v in policy_json.items() if v is not None}

    # Validate
    policy = RetentionPolicy.from_dict(policy_json)
    errors = validate_policy(policy)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": errors},
        )

    # Check if exists and update or create
    existing = store.get_retention_policy(auth.tenant_id, project_id=None)
    if existing:
        store.update_retention_policy(
            tenant_id=auth.tenant_id,
            policy_json=policy_json,
            enabled=request.enabled,
        )
    else:
        store.create_retention_policy(
            tenant_id=auth.tenant_id,
            policy_json=policy_json,
            enabled=request.enabled,
        )

    log_audit(
        "retention_policy_set",
        auth.tenant_id,
        auth.user_id,
        details={"scope": "tenant", "policy": policy_json},
    )

    # Return effective policy
    effective = get_effective_policy(auth.tenant_id, None, store)
    return RetentionPolicyResponse(
        runs_days=effective.runs_days or 0,
        jobs_days=effective.jobs_days or 0,
        reports_days=effective.reports_days or 0,
        audit_logs_days=effective.audit_logs_days or 0,
        exports_days=effective.exports_days or 0,
        enabled=request.enabled,
        is_effective=True,
        summary=summarize_policy(effective),
    )


@router.get("/retention/projects/{project_id}", response_model=RetentionPolicyResponse)
def get_project_retention_policy(
    project_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get project-level retention policy override.

    Returns the effective policy for this specific project.
    """
    store = get_compliance_store()
    effective = get_effective_policy(auth.tenant_id, project_id, store)

    return RetentionPolicyResponse(
        runs_days=effective.runs_days or 0,
        jobs_days=effective.jobs_days or 0,
        reports_days=effective.reports_days or 0,
        audit_logs_days=effective.audit_logs_days or 0,
        exports_days=effective.exports_days or 0,
        enabled=True,
        is_effective=True,
        summary=summarize_policy(effective),
    )


@router.put("/retention/projects/{project_id}", response_model=RetentionPolicyResponse)
def set_project_retention_policy(
    project_id: str,
    request: RetentionPolicyRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Set project-level retention policy override.
    """
    store = get_compliance_store()

    policy_json = {
        "runs_days": request.runs_days,
        "jobs_days": request.jobs_days,
        "reports_days": request.reports_days,
        "audit_logs_days": request.audit_logs_days,
        "exports_days": request.exports_days,
    }
    policy_json = {k: v for k, v in policy_json.items() if v is not None}

    # Validate
    policy = RetentionPolicy.from_dict(policy_json)
    errors = validate_policy(policy)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": errors},
        )

    # Check if exists and update or create
    existing = store.get_retention_policy(auth.tenant_id, project_id=project_id)
    if existing:
        store.update_retention_policy(
            tenant_id=auth.tenant_id,
            policy_json=policy_json,
            enabled=request.enabled,
            project_id=project_id,
        )
    else:
        store.create_retention_policy(
            tenant_id=auth.tenant_id,
            policy_json=policy_json,
            enabled=request.enabled,
            project_id=project_id,
        )

    log_audit(
        "retention_policy_set",
        auth.tenant_id,
        auth.user_id,
        details={"scope": "project", "project_id": project_id, "policy": policy_json},
    )

    effective = get_effective_policy(auth.tenant_id, project_id, store)
    return RetentionPolicyResponse(
        runs_days=effective.runs_days or 0,
        jobs_days=effective.jobs_days or 0,
        reports_days=effective.reports_days or 0,
        audit_logs_days=effective.audit_logs_days or 0,
        exports_days=effective.exports_days or 0,
        enabled=request.enabled,
        is_effective=True,
        summary=summarize_policy(effective),
    )


@router.delete("/retention/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_retention_policy(
    project_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Remove project-level retention policy override.

    Project will inherit tenant default after this.
    """
    store = get_compliance_store()
    deleted = store.delete_retention_policy(auth.tenant_id, project_id=project_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project retention policy not found",
        )

    log_audit(
        "retention_policy_deleted",
        auth.tenant_id,
        auth.user_id,
        details={"project_id": project_id},
    )


# -------------------------------------------------------------------------
# Legal Hold Endpoints
# -------------------------------------------------------------------------

@router.get("/holds", response_model=LegalHoldListResponse)
def list_legal_holds(
    project_id: Optional[str] = Query(default=None),
    active_only: bool = Query(default=True),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    List legal holds for tenant.
    """
    store = get_compliance_store()
    holds = store.list_legal_holds(
        tenant_id=auth.tenant_id,
        project_id=project_id,
        active_only=active_only,
    )

    items = []
    active_count = 0
    for h in holds:
        is_active = h.get("released_at") is None
        if is_active:
            active_count += 1
        items.append(LegalHoldResponse(
            id=h["id"],
            tenant_id=h["tenant_id"],
            project_id=h.get("project_id"),
            resource_type=h["resource_type"],
            resource_id=h.get("resource_id"),
            reason=h["reason"],
            created_by_user_id=h["created_by_user_id"],
            created_at=h["created_at"],
            expires_at=h.get("expires_at"),
            released_at=h.get("released_at"),
            is_active=is_active,
        ))

    return LegalHoldListResponse(
        items=items,
        total=len(items),
        active_count=active_count,
    )


@router.post("/holds", response_model=LegalHoldResponse, status_code=status.HTTP_201_CREATED)
def create_legal_hold(
    request: LegalHoldCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new legal hold.
    """
    store = get_compliance_store()

    # Normalize resource type (remove trailing 's' if present)
    resource_type = request.resource_type.rstrip("s")

    hold = store.create_legal_hold(
        tenant_id=auth.tenant_id,
        resource_type=resource_type,
        reason=request.reason,
        created_by_user_id=auth.user_id,
        project_id=request.project_id,
        resource_id=request.resource_id,
        expires_at=request.expires_at,
    )

    log_audit(
        "legal_hold_created",
        auth.tenant_id,
        auth.user_id,
        details={
            "hold_id": hold["id"],
            "resource_type": resource_type,
            "reason": request.reason,
        },
    )

    return LegalHoldResponse(
        id=hold["id"],
        tenant_id=hold["tenant_id"],
        project_id=hold.get("project_id"),
        resource_type=hold["resource_type"],
        resource_id=hold.get("resource_id"),
        reason=hold["reason"],
        created_by_user_id=hold["created_by_user_id"],
        created_at=hold["created_at"],
        expires_at=hold.get("expires_at"),
        released_at=None,
        is_active=True,
    )


@router.get("/holds/{hold_id}", response_model=LegalHoldResponse)
def get_legal_hold(
    hold_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get legal hold details.
    """
    store = get_compliance_store()
    hold = store.get_legal_hold(hold_id)

    if not hold or hold["tenant_id"] != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal hold not found",
        )

    is_active = hold.get("released_at") is None
    return LegalHoldResponse(
        id=hold["id"],
        tenant_id=hold["tenant_id"],
        project_id=hold.get("project_id"),
        resource_type=hold["resource_type"],
        resource_id=hold.get("resource_id"),
        reason=hold["reason"],
        created_by_user_id=hold["created_by_user_id"],
        created_at=hold["created_at"],
        expires_at=hold.get("expires_at"),
        released_at=hold.get("released_at"),
        is_active=is_active,
    )


@router.delete("/holds/{hold_id}", response_model=LegalHoldResponse)
def release_legal_hold(
    hold_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Release a legal hold.
    """
    store = get_compliance_store()
    hold = store.get_legal_hold(hold_id)

    if not hold or hold["tenant_id"] != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal hold not found",
        )

    released = store.release_legal_hold(hold_id)

    log_audit(
        "legal_hold_released",
        auth.tenant_id,
        auth.user_id,
        details={"hold_id": hold_id},
    )

    return LegalHoldResponse(
        id=released["id"],
        tenant_id=released["tenant_id"],
        project_id=released.get("project_id"),
        resource_type=released["resource_type"],
        resource_id=released.get("resource_id"),
        reason=released["reason"],
        created_by_user_id=released["created_by_user_id"],
        created_at=released["created_at"],
        expires_at=released.get("expires_at"),
        released_at=released.get("released_at"),
        is_active=False,
    )


@router.get("/holds/summary", response_model=HoldSummaryResponse)
def get_holds_summary(
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get summary of legal holds for tenant.
    """
    store = get_compliance_store()
    summary = get_hold_summary(store, auth.tenant_id)

    return HoldSummaryResponse(
        active_count=summary["active_count"],
        total_count=summary["total_count"],
        by_scope=summary["by_scope"],
        by_type=summary["by_type"],
    )


# -------------------------------------------------------------------------
# Purge Endpoints
# -------------------------------------------------------------------------

@router.post("/purge/dry-run", response_model=PurgeResultResponse)
def purge_dry_run(
    request: PurgeDryRunRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Preview what would be deleted without actually deleting.
    """
    store = get_compliance_store()

    # Parse categories
    categories = None
    if request.categories:
        categories = [
            ResourceCategory(c.rstrip("s"))
            for c in request.categories
            if c.rstrip("s") in [cat.value for cat in ResourceCategory]
        ]

    result = dry_run_retention(
        compliance_store=store,
        tenant_id=auth.tenant_id,
        project_id=request.project_id,
        categories=categories,
    )

    log_audit(
        "purge_dry_run",
        auth.tenant_id,
        auth.user_id,
        details={"project_id": request.project_id, "total_to_delete": result.total_to_delete},
    )

    return PurgeResultResponse(
        mode=result.mode,
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        success=result.success,
        error=result.error,
        total_found=result.total_found,
        total_to_delete=result.total_to_delete,
        total_deleted=result.total_deleted,
        total_skipped_held=result.total_skipped_held,
        total_skipped_error=result.total_skipped_error,
        hit_limit=result.hit_limit,
        categories=[
            PurgeCategoryStats(
                category=c.category,
                retention_days=c.retention_days,
                total_found=c.total_found,
                to_delete=c.to_delete,
                deleted=c.deleted,
                skipped_held=c.skipped_held,
                skipped_error=c.skipped_error,
            )
            for c in result.categories
        ],
    )


@router.post("/purge/execute", response_model=PurgeResultResponse)
def purge_execute(
    request: PurgeExecuteRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Execute retention purge.

    Actually deletes resources according to policy.
    """
    store = get_compliance_store()

    # Parse categories
    categories = None
    if request.categories:
        categories = [
            ResourceCategory(c.rstrip("s"))
            for c in request.categories
            if c.rstrip("s") in [cat.value for cat in ResourceCategory]
        ]

    result = execute_retention(
        compliance_store=store,
        tenant_id=auth.tenant_id,
        project_id=request.project_id,
        categories=categories,
        max_deletions=request.max_deletions or 10000,
    )

    log_audit(
        "purge_executed",
        auth.tenant_id,
        auth.user_id,
        details={
            "project_id": request.project_id,
            "total_deleted": result.total_deleted,
            "success": result.success,
        },
    )

    return PurgeResultResponse(
        mode=result.mode,
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        success=result.success,
        error=result.error,
        total_found=result.total_found,
        total_to_delete=result.total_to_delete,
        total_deleted=result.total_deleted,
        total_skipped_held=result.total_skipped_held,
        total_skipped_error=result.total_skipped_error,
        hit_limit=result.hit_limit,
        categories=[
            PurgeCategoryStats(
                category=c.category,
                retention_days=c.retention_days,
                total_found=c.total_found,
                to_delete=c.to_delete,
                deleted=c.deleted,
                skipped_held=c.skipped_held,
                skipped_error=c.skipped_error,
            )
            for c in result.categories
        ],
    )


@router.get("/purge/history", response_model=PurgeHistoryResponse)
def get_purge_history(
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get purge run history.
    """
    store = get_compliance_store()
    runs = list_purge_history(store, auth.tenant_id, project_id, limit)

    return PurgeHistoryResponse(
        items=runs,
        total=len(runs),
    )


@router.get("/purge/{run_id}")
def get_purge_run(
    run_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get purge run details.
    """
    store = get_compliance_store()
    run = get_purge_status(store, run_id)

    if not run or run["tenant_id"] != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purge run not found",
        )

    return run
