"""
Usage API Router (v4.0.0).

Provides endpoints for viewing usage data:
- GET /usage - Tenant-level usage summary
- GET /usage/daily - Daily usage history
- GET /projects/{id}/usage - Project-level usage
- GET /usage/export/csv - Export usage as CSV
"""

import os
import io
import csv
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from quota_store import QuotaStore
from quota_engine import get_quota_snapshot
from auth_deps import get_auth_context, AuthContext, require_role
from auth_config import Role


# -----------------------------------------------------------------------------
# Router
# -----------------------------------------------------------------------------

router = APIRouter(prefix="/api/bess-dispatch", tags=["usage"])


# -----------------------------------------------------------------------------
# Quota Store dependency
# -----------------------------------------------------------------------------

QUOTA_STORE_PATH = os.getenv("QUOTA_STORE_PATH", "/data/quotas.sqlite")
_quota_store: Optional[QuotaStore] = None


def get_quota_store() -> QuotaStore:
    """Get or create the quota store singleton."""
    global _quota_store
    if _quota_store is None:
        _quota_store = QuotaStore(db_path=QUOTA_STORE_PATH)
    return _quota_store


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------

class QuotaUsageSummary(BaseModel):
    """Summary of quota usage for a single quota type."""
    quota_name: str
    limit: Optional[int] = None
    used: int = 0
    remaining: Optional[int] = None
    usage_pct: Optional[float] = None


class TenantUsageResponse(BaseModel):
    """Tenant-level usage summary."""
    tenant_id: str
    plan_id: str
    date: str = Field(description="Date for usage data (YYYY-MM-DD)")
    quotas: List[QuotaUsageSummary] = Field(default_factory=list)
    reset_at: str = Field(description="When quotas reset (ISO 8601)")


class ProjectUsageResponse(BaseModel):
    """Project-level usage summary."""
    tenant_id: str
    project_id: str
    plan_id: str
    date: str = Field(description="Date for usage data (YYYY-MM-DD)")
    quotas: List[QuotaUsageSummary] = Field(default_factory=list)
    has_overrides: bool = False
    reset_at: str = Field(description="When quotas reset (ISO 8601)")


class DailyUsageRecord(BaseModel):
    """Daily usage record."""
    date: str
    project_id: str
    counters: Dict[str, int] = Field(default_factory=dict)
    bytes_used: Dict[str, int] = Field(default_factory=dict)


class DailyUsageResponse(BaseModel):
    """Response for daily usage history."""
    tenant_id: str
    records: List[DailyUsageRecord] = Field(default_factory=list)
    total_days: int = 0


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def compute_usage_summary(
    limits: Dict[str, int],
    used: Dict[str, int],
) -> List[QuotaUsageSummary]:
    """Compute usage summary for each quota type."""
    summaries = []

    # Define standard quota names
    quota_names = ["jobs_per_day", "reports_per_day", "shares_total", "storage_mb", "projects_total"]

    for name in quota_names:
        limit = limits.get(name)
        usage = used.get(name, 0)

        if limit is None:
            # Quota not defined in plan
            summaries.append(QuotaUsageSummary(
                quota_name=name,
                limit=None,
                used=usage,
                remaining=None,
                usage_pct=None,
            ))
        elif limit == 0:
            # Unlimited
            summaries.append(QuotaUsageSummary(
                quota_name=name,
                limit=0,
                used=usage,
                remaining=None,
                usage_pct=None,
            ))
        else:
            remaining = max(0, limit - usage)
            usage_pct = round((usage / limit) * 100, 1) if limit > 0 else 0.0
            summaries.append(QuotaUsageSummary(
                quota_name=name,
                limit=limit,
                used=usage,
                remaining=remaining,
                usage_pct=usage_pct,
            ))

    return summaries


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.get("/usage", response_model=TenantUsageResponse)
async def get_tenant_usage(
    auth: AuthContext = Depends(get_auth_context),
    store: QuotaStore = Depends(get_quota_store),
) -> TenantUsageResponse:
    """
    Get tenant-level usage summary.

    Returns aggregated usage across all projects for today.
    """
    tenant_id = auth.tenant_id
    today = store.get_today_date()

    # Get tenant settings
    settings = store.get_tenant_settings(tenant_id)
    if settings is None:
        settings = store.upsert_tenant_settings(tenant_id)

    plan_id = settings.plan_id

    # Get plan limits
    plan = store.get_plan(plan_id)
    if plan is None:
        plan = store.get_default_plan()

    limits = plan.limits_json if plan else {}

    # Aggregate usage across all projects
    usage_records = store.list_usage_daily(tenant_id, from_date=today, to_date=today)

    aggregated = {}
    for record in usage_records:
        for key, value in record.counters_json.items():
            aggregated[key] = aggregated.get(key, 0) + value

    # Compute summaries
    quotas = compute_usage_summary(limits, aggregated)

    # Get reset time from quota engine
    from quota_engine import get_next_reset_time
    reset_at = get_next_reset_time()

    return TenantUsageResponse(
        tenant_id=tenant_id,
        plan_id=plan_id,
        date=today,
        quotas=quotas,
        reset_at=reset_at,
    )


@router.get("/usage/daily", response_model=DailyUsageResponse)
async def get_daily_usage(
    auth: AuthContext = Depends(get_auth_context),
    store: QuotaStore = Depends(get_quota_store),
    days: int = Query(default=7, ge=1, le=90, description="Number of days to retrieve"),
    project_id: Optional[str] = Query(default=None, description="Filter by project ID"),
) -> DailyUsageResponse:
    """
    Get daily usage history.

    Returns usage records for the specified number of days.
    Optionally filter by project_id.
    """
    tenant_id = auth.tenant_id

    # Calculate date range
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days - 1)).isoformat()
    date_to = today.isoformat()

    # Get usage records
    records = store.list_usage_daily(
        tenant_id=tenant_id,
        project_id=project_id,
        from_date=date_from,
        to_date=date_to,
    )

    # Convert to response format
    daily_records = [
        DailyUsageRecord(
            date=r.date,
            project_id=r.project_id,
            counters=r.counters_json,
            bytes_used=r.bytes_json,
        )
        for r in records
    ]

    return DailyUsageResponse(
        tenant_id=tenant_id,
        records=daily_records,
        total_days=len(set(r.date for r in daily_records)),
    )


@router.get("/projects/{project_id}/usage", response_model=ProjectUsageResponse)
async def get_project_usage(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
    store: QuotaStore = Depends(get_quota_store),
) -> ProjectUsageResponse:
    """
    Get project-level usage summary.

    Returns usage for a specific project, taking into account project overrides.
    """
    tenant_id = auth.tenant_id

    # Get quota snapshot which includes effective limits
    snapshot = get_quota_snapshot(tenant_id, project_id)

    # Check if project has overrides
    project_quota = store.get_project_quota(tenant_id, project_id)
    has_overrides = project_quota is not None and bool(project_quota.overrides_json)

    # Compute summaries
    quotas = compute_usage_summary(snapshot.limits, snapshot.used_today)

    return ProjectUsageResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=snapshot.plan_id,
        date=store.get_today_date(),
        quotas=quotas,
        has_overrides=has_overrides,
        reset_at=snapshot.reset_at,
    )


@router.get("/usage/export/csv")
async def export_usage_csv(
    auth: AuthContext = Depends(get_auth_context),
    store: QuotaStore = Depends(get_quota_store),
    days: int = Query(default=30, ge=1, le=365, description="Number of days to export"),
    project_id: Optional[str] = Query(default=None, description="Filter by project ID"),
) -> Response:
    """
    Export usage data as CSV.

    Returns CSV file with daily usage records.
    """
    tenant_id = auth.tenant_id

    # Calculate date range
    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days - 1)).isoformat()
    date_to = today.isoformat()

    # Get usage records
    records = store.list_usage_daily(
        tenant_id=tenant_id,
        project_id=project_id,
        from_date=date_from,
        to_date=date_to,
    )

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "date",
        "project_id",
        "jobs_per_day",
        "reports_per_day",
        "shares_total",
        "storage_mb",
        "projects_total",
        "bytes_request",
        "bytes_response",
    ])

    # Data rows
    for record in records:
        counters = record.counters_json
        bytes_data = record.bytes_json
        writer.writerow([
            record.date,
            record.project_id,
            counters.get("jobs_per_day", 0),
            counters.get("reports_per_day", 0),
            counters.get("shares_total", 0),
            counters.get("storage_mb", 0),
            counters.get("projects_total", 0),
            bytes_data.get("request", 0),
            bytes_data.get("response", 0),
        ])

    csv_content = output.getvalue()

    # Generate filename
    filename = f"usage_{tenant_id}_{date_from}_to_{date_to}.csv"
    if project_id:
        filename = f"usage_{tenant_id}_{project_id}_{date_from}_to_{date_to}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/projects/{project_id}/usage/export/csv")
async def export_project_usage_csv(
    project_id: str,
    auth: AuthContext = Depends(get_auth_context),
    store: QuotaStore = Depends(get_quota_store),
    days: int = Query(default=30, ge=1, le=365, description="Number of days to export"),
) -> Response:
    """
    Export project-specific usage data as CSV.

    Returns CSV file with daily usage records for a specific project.
    """
    # Reuse the main export endpoint with project_id filter
    return await export_usage_csv(auth=auth, store=store, days=days, project_id=project_id)
