"""
Quota Engine (v4.0.0).

Computes effective limits by combining:
1. Plan limits (base)
2. Project-level overrides (if any)

Returns a QuotaSnapshot with:
- limits: effective limit values
- used_today: current usage for today
- remaining: limits - used_today
- reset_at: when the daily counters reset (midnight UTC)
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from quota_store import QuotaStore, Plan, ProjectQuota


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


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class QuotaSnapshot:
    """
    Snapshot of quota limits and usage for a tenant/project.

    limits: Effective limits after applying overrides
    used_today: Current usage counters for today
    remaining: Remaining quota (limits - used_today)
    reset_at: When daily limits reset (ISO 8601)
    """
    tenant_id: str
    project_id: str
    plan_id: str
    limits: Dict[str, int] = field(default_factory=dict)
    used_today: Dict[str, int] = field(default_factory=dict)
    remaining: Dict[str, int] = field(default_factory=dict)
    reset_at: str = ""

    def is_exceeded(self, quota_name: str) -> bool:
        """Check if a specific quota is exceeded."""
        if quota_name not in self.limits:
            return False
        limit = self.limits[quota_name]
        used = self.used_today.get(quota_name, 0)
        return used >= limit

    def get_remaining(self, quota_name: str) -> Optional[int]:
        """Get remaining quota for a specific limit."""
        if quota_name not in self.limits:
            return None
        limit = self.limits[quota_name]
        used = self.used_today.get(quota_name, 0)
        return max(0, limit - used)


# -----------------------------------------------------------------------------
# Quota Engine
# -----------------------------------------------------------------------------

def get_next_reset_time() -> str:
    """Get the next midnight UTC as ISO 8601 string."""
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return tomorrow.isoformat()


def compute_effective_limits(
    plan: Plan,
    project_overrides: Optional[ProjectQuota] = None,
) -> Dict[str, int]:
    """
    Compute effective limits by applying overrides to plan limits.

    Override rules:
    - Project override takes precedence over plan limit
    - If override is 0, it means "no limit" (unlimited)
    - If no override, use plan limit
    """
    limits = dict(plan.limits_json)

    if project_overrides:
        for key, value in project_overrides.overrides_json.items():
            if value is not None:
                limits[key] = value

    return limits


def get_quota_snapshot(
    tenant_id: str,
    project_id: str,
) -> QuotaSnapshot:
    """
    Get a complete quota snapshot for a tenant/project.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID

    Returns:
        QuotaSnapshot with limits, usage, remaining, and reset time
    """
    store = get_quota_store()

    # Get tenant settings (or create with defaults)
    settings = store.get_tenant_settings(tenant_id)
    if settings is None:
        settings = store.upsert_tenant_settings(tenant_id)

    # Get the plan
    plan = store.get_plan(settings.plan_id)
    if plan is None:
        # Fall back to default plan
        plan = store.get_default_plan()
        if plan is None:
            # No plans exist - return empty snapshot
            return QuotaSnapshot(
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id="unknown",
                reset_at=get_next_reset_time(),
            )

    # Get project overrides (if any)
    project_overrides = store.get_project_quota(tenant_id, project_id)

    # Compute effective limits
    limits = compute_effective_limits(plan, project_overrides)

    # Get today's usage
    today = store.get_today_date()
    usage = store.get_usage_daily(tenant_id, project_id, today)
    used_today = usage.counters_json if usage else {}

    # Compute remaining
    remaining = {}
    for key, limit in limits.items():
        used = used_today.get(key, 0)
        remaining[key] = max(0, limit - used)

    return QuotaSnapshot(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=settings.plan_id,
        limits=limits,
        used_today=used_today,
        remaining=remaining,
        reset_at=get_next_reset_time(),
    )


def check_quota(
    tenant_id: str,
    project_id: str,
    quota_name: str,
    increment: int = 1,
) -> Dict[str, Any]:
    """
    Check if an action would exceed quota.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        quota_name: Name of quota to check (e.g., 'jobs_per_day')
        increment: Amount to add (for checking if n items would exceed)

    Returns:
        Dict with:
        - allowed: bool - whether the action is allowed
        - limit: int - the limit value
        - used: int - current usage
        - remaining: int - remaining after this action (if allowed)
        - reset_at: str - when limits reset
    """
    snapshot = get_quota_snapshot(tenant_id, project_id)

    limit = snapshot.limits.get(quota_name)
    if limit is None:
        # No limit defined - allow
        return {
            "allowed": True,
            "limit": None,
            "used": 0,
            "remaining": None,
            "reset_at": snapshot.reset_at,
        }

    # 0 means unlimited
    if limit == 0:
        return {
            "allowed": True,
            "limit": 0,
            "used": snapshot.used_today.get(quota_name, 0),
            "remaining": None,
            "reset_at": snapshot.reset_at,
        }

    used = snapshot.used_today.get(quota_name, 0)
    would_use = used + increment

    allowed = would_use <= limit

    return {
        "allowed": allowed,
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - would_use) if allowed else 0,
        "reset_at": snapshot.reset_at,
    }


def get_seconds_until_reset() -> int:
    """Get seconds until next quota reset (midnight UTC)."""
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return int((tomorrow - now).total_seconds())
