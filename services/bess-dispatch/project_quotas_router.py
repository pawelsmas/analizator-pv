"""
Project Quotas API router (v4.0.0).

Endpoints:
- GET /projects/{id}/quotas - Get project quota overrides
- PATCH /projects/{id}/quotas - Update project quota overrides

Requires admin or project owner role.
"""

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth_config import AuthContext, Role
from auth_deps import require_role
from audit_store import log_audit
from quota_store import QuotaStore


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

QUOTA_STORE_PATH = os.getenv("QUOTA_STORE_PATH", "/data/quotas.sqlite")

_quota_store: Optional[QuotaStore] = None


def get_quota_store() -> QuotaStore:
    """Get or create the quota store singleton."""
    global _quota_store
    if _quota_store is None:
        _quota_store = QuotaStore(db_path=QUOTA_STORE_PATH)
    return _quota_store


router = APIRouter(prefix="/projects", tags=["project-quotas"])


# -----------------------------------------------------------------------------
# Request/Response models
# -----------------------------------------------------------------------------

class QuotaOverrides(BaseModel):
    """Quota override values."""
    jobs_per_day: Optional[int] = Field(None, ge=0, description="Override for jobs per day limit")
    reports_per_day: Optional[int] = Field(None, ge=0, description="Override for reports per day")
    shares_total: Optional[int] = Field(None, ge=0, description="Override for total shares")
    storage_mb: Optional[int] = Field(None, ge=0, description="Override for storage in MB")


class ProjectQuotaResponse(BaseModel):
    """Project quota response model."""
    tenant_id: str
    project_id: str
    overrides: QuotaOverrides
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProjectQuotaUpdateRequest(BaseModel):
    """Request to update project quota overrides."""
    overrides: QuotaOverrides = Field(
        ...,
        description="Quota overrides to set. Only specified values will be updated."
    )


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.get("/{project_id}/quotas", response_model=ProjectQuotaResponse)
def get_project_quotas(
    project_id: str,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    """
    Get quota overrides for a project.

    Returns the project-specific quota overrides. If none exist,
    returns empty overrides.
    """
    store = get_quota_store()

    quota = store.get_project_quota(auth.tenant_id, project_id)

    if quota is None:
        return ProjectQuotaResponse(
            tenant_id=auth.tenant_id,
            project_id=project_id,
            overrides=QuotaOverrides(),
        )

    return ProjectQuotaResponse(
        tenant_id=quota.tenant_id,
        project_id=quota.project_id,
        overrides=QuotaOverrides(**quota.overrides_json),
        created_at=quota.created_at,
        updated_at=quota.updated_at,
    )


@router.patch("/{project_id}/quotas", response_model=ProjectQuotaResponse)
def update_project_quotas(
    project_id: str,
    request: ProjectQuotaUpdateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Update quota overrides for a project.

    Only specified values will be updated. Other overrides remain unchanged.
    Requires admin role.
    """
    store = get_quota_store()

    # Build overrides dict, excluding None values
    overrides = {
        k: v
        for k, v in request.overrides.model_dump().items()
        if v is not None
    }

    if not overrides:
        # No changes requested
        return get_project_quotas(project_id, auth)

    quota = store.upsert_project_quota(
        tenant_id=auth.tenant_id,
        project_id=project_id,
        overrides=overrides,
    )

    # Audit log
    log_audit(
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        action="project_quota_update",
        resource_type="project_quota",
        resource_id=project_id,
        details={"overrides": overrides},
    )

    return ProjectQuotaResponse(
        tenant_id=quota.tenant_id,
        project_id=quota.project_id,
        overrides=QuotaOverrides(**quota.overrides_json),
        created_at=quota.created_at,
        updated_at=quota.updated_at,
    )
