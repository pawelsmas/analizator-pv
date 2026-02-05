"""
Plans and Tenant Settings API router (v4.0.0).

Endpoints:
- GET /plans - List available plans
- GET /tenant/settings - Get tenant settings
- PATCH /tenant/settings - Update tenant settings (plan, billing status)

Requires admin role for tenant settings modifications.
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth_config import AuthContext, Role
from auth_deps import require_role
from audit_store import log_audit
from quota_store import QuotaStore, Plan, TenantSettings


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


router = APIRouter(tags=["plans"])


# -----------------------------------------------------------------------------
# Request/Response models
# -----------------------------------------------------------------------------

class PlanLimits(BaseModel):
    """Plan limits configuration."""
    jobs_per_day: Optional[int] = None
    reports_per_day: Optional[int] = None
    shares_total: Optional[int] = None
    storage_mb: Optional[int] = None
    projects_total: Optional[int] = None


class PlanResponse(BaseModel):
    """Plan response model."""
    id: str
    name: str
    limits: PlanLimits
    is_default: bool = False


class PlansListResponse(BaseModel):
    """Response for listing plans."""
    items: List[PlanResponse]
    total: int


class TenantSettingsResponse(BaseModel):
    """Tenant settings response model."""
    tenant_id: str
    plan_id: str
    plan_name: str
    billing_status: str
    grace_mode_until: Optional[str] = None
    limits: PlanLimits
    created_at: str
    updated_at: str


class TenantSettingsUpdateRequest(BaseModel):
    """Request to update tenant settings."""
    plan_id: Optional[str] = Field(None, description="New plan ID")
    billing_status: Optional[str] = Field(
        None,
        description="Billing status: active, suspended, grace, cancelled"
    )
    grace_mode_until: Optional[str] = Field(
        None,
        description="Grace mode expiration (ISO 8601)"
    )


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def plan_to_response(plan: Plan) -> PlanResponse:
    """Convert Plan dataclass to response model."""
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        limits=PlanLimits(**plan.limits_json),
        is_default=plan.is_default,
    )


def settings_to_response(
    settings: TenantSettings,
    plan: Optional[Plan],
) -> TenantSettingsResponse:
    """Convert TenantSettings and Plan to response model."""
    limits = PlanLimits()
    plan_name = "Unknown"
    if plan:
        limits = PlanLimits(**plan.limits_json)
        plan_name = plan.name

    return TenantSettingsResponse(
        tenant_id=settings.tenant_id,
        plan_id=settings.plan_id,
        plan_name=plan_name,
        billing_status=settings.billing_status,
        grace_mode_until=settings.grace_mode_until,
        limits=limits,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.get("/plans", response_model=PlansListResponse)
def list_plans(auth: AuthContext = Depends(require_role(Role.VIEWER))):
    """
    List all available plans.

    Returns all plans with their limits. Any authenticated user can view plans.
    """
    store = get_quota_store()
    plans = store.list_plans()

    return PlansListResponse(
        items=[plan_to_response(p) for p in plans],
        total=len(plans),
    )


@router.get("/tenant/settings", response_model=TenantSettingsResponse)
def get_tenant_settings(auth: AuthContext = Depends(require_role(Role.VIEWER))):
    """
    Get current tenant settings.

    Returns the tenant's plan, billing status, and effective limits.
    Creates default settings if none exist.
    """
    store = get_quota_store()

    # Get or create tenant settings
    settings = store.get_tenant_settings(auth.tenant_id)
    if settings is None:
        settings = store.upsert_tenant_settings(auth.tenant_id)

    # Get the plan
    plan = store.get_plan(settings.plan_id)

    return settings_to_response(settings, plan)


@router.patch("/tenant/settings", response_model=TenantSettingsResponse)
def update_tenant_settings(
    request: TenantSettingsUpdateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Update tenant settings.

    Allows admin to change plan or billing status.
    Requires admin role.

    Validation:
    - plan_id must be a valid plan ID
    - billing_status must be one of: active, suspended, grace, cancelled
    """
    store = get_quota_store()

    # Validate plan_id if provided
    if request.plan_id is not None:
        plan = store.get_plan(request.plan_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan_id: {request.plan_id}",
            )

    # Validate billing_status if provided
    valid_statuses = {"active", "suspended", "grace", "cancelled"}
    if request.billing_status is not None:
        if request.billing_status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid billing_status: {request.billing_status}. "
                       f"Must be one of: {', '.join(valid_statuses)}",
            )

    # Update settings
    settings = store.upsert_tenant_settings(
        tenant_id=auth.tenant_id,
        plan_id=request.plan_id,
        billing_status=request.billing_status,
        grace_mode_until=request.grace_mode_until,
    )

    # Get the plan for response
    plan = store.get_plan(settings.plan_id)

    # Audit log
    log_audit(
        tenant_id=auth.tenant_id,
        actor_id=auth.user_id,
        action="tenant_settings_update",
        resource_type="tenant_settings",
        resource_id=auth.tenant_id,
        details={
            "plan_id": request.plan_id,
            "billing_status": request.billing_status,
            "grace_mode_until": request.grace_mode_until,
        },
    )

    return settings_to_response(settings, plan)
