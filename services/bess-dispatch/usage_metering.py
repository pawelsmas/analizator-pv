"""
Usage Metering Module (v4.0.0).

Provides:
- Metering helpers for tracking usage counters and bytes
- Idempotency-safe metering (no double counting on replays)
- Integration with usage_daily storage

Metered actions:
- runs_created
- jobs_enqueued
- reports_generated
- reports_downloaded
- shares_created
- shared_access_ok

Metered bytes:
- artifact_bytes_written
- artifact_bytes_served
"""

import os
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, Optional, Set

from quota_store import QuotaStore


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

QUOTA_STORE_PATH = os.getenv("QUOTA_STORE_PATH", "/data/quotas.sqlite")
METERING_ENABLED = os.getenv("METERING_ENABLED", "true").lower() in ("true", "1", "yes")

_quota_store: Optional[QuotaStore] = None

# In-memory cache of metered idempotency keys to prevent double counting
# Format: {(tenant_id, project_id, idempotency_key): set of metered_actions}
_metered_keys: Dict[tuple, Set[str]] = {}


def get_quota_store() -> QuotaStore:
    """Get or create the quota store singleton."""
    global _quota_store
    if _quota_store is None:
        _quota_store = QuotaStore(db_path=QUOTA_STORE_PATH)
    return _quota_store


def get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -----------------------------------------------------------------------------
# Idempotency-Safe Metering
# -----------------------------------------------------------------------------

def is_already_metered(
    tenant_id: str,
    project_id: str,
    idempotency_key: Optional[str],
    action: str,
) -> bool:
    """
    Check if an action has already been metered for this idempotency key.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        idempotency_key: Optional idempotency key for deduplication
        action: The action being metered

    Returns:
        True if already metered, False otherwise
    """
    if idempotency_key is None:
        return False

    key = (tenant_id, project_id, idempotency_key)
    metered_actions = _metered_keys.get(key, set())
    return action in metered_actions


def mark_as_metered(
    tenant_id: str,
    project_id: str,
    idempotency_key: Optional[str],
    action: str,
) -> None:
    """
    Mark an action as metered for this idempotency key.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        idempotency_key: Optional idempotency key for deduplication
        action: The action being metered
    """
    if idempotency_key is None:
        return

    key = (tenant_id, project_id, idempotency_key)
    if key not in _metered_keys:
        _metered_keys[key] = set()
    _metered_keys[key].add(action)


def clear_metered_keys() -> None:
    """Clear the in-memory metered keys cache. Useful for testing."""
    global _metered_keys
    _metered_keys = {}


# -----------------------------------------------------------------------------
# Metering Functions
# -----------------------------------------------------------------------------

def meter_counter(
    tenant_id: str,
    project_id: str,
    counter_name: str,
    increment: int = 1,
    idempotency_key: Optional[str] = None,
) -> bool:
    """
    Increment a usage counter, respecting idempotency.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        counter_name: Name of counter (e.g., 'jobs_enqueued')
        increment: Amount to increment (default 1)
        idempotency_key: Optional key to prevent double counting

    Returns:
        True if metered, False if skipped due to idempotency
    """
    if not METERING_ENABLED:
        return False

    # Check idempotency
    if is_already_metered(tenant_id, project_id, idempotency_key, counter_name):
        return False

    # Record usage
    store = get_quota_store()
    store.upsert_usage_daily(
        tenant_id=tenant_id,
        project_id=project_id,
        usage_date=get_today_date(),
        counter_increments={counter_name: increment},
    )

    # Mark as metered
    mark_as_metered(tenant_id, project_id, idempotency_key, counter_name)

    return True


def meter_bytes(
    tenant_id: str,
    project_id: str,
    bytes_name: str,
    bytes_count: int,
    idempotency_key: Optional[str] = None,
) -> bool:
    """
    Record bytes usage, respecting idempotency.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        bytes_name: Name of bytes counter (e.g., 'artifact_bytes_written')
        bytes_count: Number of bytes
        idempotency_key: Optional key to prevent double counting

    Returns:
        True if metered, False if skipped due to idempotency
    """
    if not METERING_ENABLED:
        return False

    # Check idempotency
    action = f"bytes:{bytes_name}"
    if is_already_metered(tenant_id, project_id, idempotency_key, action):
        return False

    # Record usage
    store = get_quota_store()
    store.upsert_usage_daily(
        tenant_id=tenant_id,
        project_id=project_id,
        usage_date=get_today_date(),
        bytes_increments={bytes_name: bytes_count},
    )

    # Mark as metered
    mark_as_metered(tenant_id, project_id, idempotency_key, action)

    return True


# -----------------------------------------------------------------------------
# Convenience Functions
# -----------------------------------------------------------------------------

def meter_job_enqueued(
    tenant_id: str,
    project_id: str,
    idempotency_key: Optional[str] = None,
) -> bool:
    """Record a job enqueued event."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="jobs_enqueued",
        idempotency_key=idempotency_key,
    )


def meter_run_created(
    tenant_id: str,
    project_id: str,
    run_id: Optional[str] = None,
) -> bool:
    """Record a run created event."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="runs_created",
        idempotency_key=run_id,  # Use run_id as idempotency key
    )


def meter_report_generated(
    tenant_id: str,
    project_id: str,
    report_id: Optional[str] = None,
) -> bool:
    """Record a report generated event."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="reports_generated",
        idempotency_key=report_id,
    )


def meter_report_downloaded(
    tenant_id: str,
    project_id: str,
) -> bool:
    """Record a report downloaded event (no idempotency - each download counts)."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="reports_downloaded",
    )


def meter_share_created(
    tenant_id: str,
    project_id: str,
    share_id: Optional[str] = None,
) -> bool:
    """Record a share created event."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="shares_created",
        idempotency_key=share_id,
    )


def meter_shared_access(
    tenant_id: str,
    project_id: str,
) -> bool:
    """Record a shared access event (no idempotency - each access counts)."""
    return meter_counter(
        tenant_id=tenant_id,
        project_id=project_id,
        counter_name="shared_access_ok",
    )


def meter_artifact_written(
    tenant_id: str,
    project_id: str,
    bytes_count: int,
    artifact_id: Optional[str] = None,
) -> bool:
    """Record bytes written to an artifact."""
    return meter_bytes(
        tenant_id=tenant_id,
        project_id=project_id,
        bytes_name="artifact_bytes_written",
        bytes_count=bytes_count,
        idempotency_key=artifact_id,
    )


def meter_artifact_served(
    tenant_id: str,
    project_id: str,
    bytes_count: int,
) -> bool:
    """Record bytes served from artifacts (no idempotency - each serve counts)."""
    return meter_bytes(
        tenant_id=tenant_id,
        project_id=project_id,
        bytes_name="artifact_bytes_served",
        bytes_count=bytes_count,
    )


# -----------------------------------------------------------------------------
# Usage Summary
# -----------------------------------------------------------------------------

def get_today_usage(
    tenant_id: str,
    project_id: str,
) -> Dict[str, Any]:
    """
    Get today's usage for a tenant/project.

    Returns:
        Dict with counters and bytes for today
    """
    store = get_quota_store()
    today = get_today_date()
    usage = store.get_usage_daily(tenant_id, project_id, today)

    if usage is None:
        return {
            "date": today,
            "counters": {},
            "bytes": {},
        }

    return {
        "date": today,
        "counters": usage.counters_json,
        "bytes": usage.bytes_json,
    }
