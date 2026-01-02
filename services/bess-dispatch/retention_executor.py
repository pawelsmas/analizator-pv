"""
Retention Executor - Execute purge operations (v4.3.0 PR4).

Provides:
- execute_retention() - main entry point for purge operations
- dry_run_retention() - preview what would be deleted
- PurgeResult - result model with deleted/skipped/held counts
- Safety limits (max deletions per run)
- Advisory lock support

Usage:
    from retention_executor import (
        execute_retention,
        dry_run_retention,
        PurgeMode,
    )

    # Dry run to preview
    result = dry_run_retention(compliance_store, tenant_id, project_id)
    print(f"Would delete: {result.total_to_delete}")

    # Execute purge
    result = execute_retention(compliance_store, tenant_id, project_id)
    print(f"Deleted: {result.total_deleted}")
"""

import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Callable

from pydantic import BaseModel, Field

from compliance_store import ComplianceStore, PurgeMode
from retention_policy_helper import (
    RetentionPolicy,
    ResourceCategory,
    get_effective_policy,
    compute_cutoff_date,
)
from legal_hold_helper import (
    LegalHoldMatcher,
    ResourceRef,
    HoldViolationError,
)


# Safety limits
MAX_DELETIONS_PER_RUN = 10000  # Maximum resources to delete in single run
DEFAULT_BATCH_SIZE = 100      # Default batch size for deletions


class ResourceStore(Protocol):
    """Protocol for resource stores that can list and delete resources."""

    def list_resources(
        self,
        tenant_id: str,
        resource_type: str,
        project_id: Optional[str] = None,
        created_before: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List resources matching criteria."""
        ...

    def delete_resource(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Delete a specific resource."""
        ...


class PurgeStats(BaseModel):
    """Statistics for a single resource category."""

    category: str = Field(description="Resource category")
    retention_days: int = Field(description="Retention period in days")
    cutoff_date: Optional[str] = Field(default=None, description="Cutoff date ISO")
    total_found: int = Field(default=0, description="Total resources found")
    to_delete: int = Field(default=0, description="Resources eligible for deletion")
    deleted: int = Field(default=0, description="Resources actually deleted")
    skipped_held: int = Field(default=0, description="Skipped due to legal hold")
    skipped_error: int = Field(default=0, description="Skipped due to errors")


class PurgeResult(BaseModel):
    """Result of a purge operation."""

    mode: str = Field(description="Execution mode (dry_run or execute)")
    tenant_id: str = Field(description="Tenant ID")
    project_id: Optional[str] = Field(default=None, description="Project ID if scoped")
    started_at: str = Field(description="Start time ISO")
    finished_at: Optional[str] = Field(default=None, description="End time ISO")
    success: bool = Field(default=False, description="Whether operation succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    # Aggregate counts
    total_found: int = Field(default=0, description="Total resources found")
    total_to_delete: int = Field(default=0, description="Total eligible for deletion")
    total_deleted: int = Field(default=0, description="Total actually deleted")
    total_skipped_held: int = Field(default=0, description="Total skipped due to holds")
    total_skipped_error: int = Field(default=0, description="Total skipped due to errors")

    # Per-category stats
    categories: List[PurgeStats] = Field(default_factory=list)

    # Safety info
    hit_limit: bool = Field(default=False, description="Whether deletion limit was hit")
    max_deletions: int = Field(default=MAX_DELETIONS_PER_RUN)

    def to_summary(self) -> Dict[str, Any]:
        """Convert to summary dictionary for storage."""
        return {
            "mode": self.mode,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "success": self.success,
            "total_found": self.total_found,
            "total_to_delete": self.total_to_delete,
            "total_deleted": self.total_deleted,
            "total_skipped_held": self.total_skipped_held,
            "total_skipped_error": self.total_skipped_error,
            "hit_limit": self.hit_limit,
            "categories": [
                {
                    "category": c.category,
                    "retention_days": c.retention_days,
                    "deleted": c.deleted,
                    "skipped_held": c.skipped_held,
                }
                for c in self.categories
            ],
        }


# Advisory lock for concurrent execution prevention
_execution_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_execution_lock(tenant_id: str, project_id: Optional[str]) -> threading.Lock:
    """Get or create execution lock for tenant/project."""
    key = f"{tenant_id}:{project_id or 'ALL'}"
    with _locks_lock:
        if key not in _execution_locks:
            _execution_locks[key] = threading.Lock()
        return _execution_locks[key]


def _collect_resources_to_purge(
    compliance_store: ComplianceStore,
    resource_store: Optional[ResourceStore],
    tenant_id: str,
    project_id: Optional[str],
    policy: RetentionPolicy,
    matcher: LegalHoldMatcher,
    max_per_category: int = 1000,
) -> Dict[ResourceCategory, List[Dict[str, Any]]]:
    """
    Collect resources eligible for purge.

    Args:
        compliance_store: ComplianceStore instance
        resource_store: Optional ResourceStore for actual resources
        tenant_id: Tenant ID
        project_id: Project ID (None for tenant-wide)
        policy: Effective retention policy
        matcher: LegalHoldMatcher for checking holds
        max_per_category: Max resources to collect per category

    Returns:
        Dictionary mapping category to list of resources
    """
    result: Dict[ResourceCategory, List[Dict[str, Any]]] = {}

    for category in ResourceCategory:
        cutoff = compute_cutoff_date(category, policy)
        if cutoff is None:
            # Indefinite retention
            result[category] = []
            continue

        resources: List[Dict[str, Any]] = []

        # For now, we'll simulate resources from the compliance store
        # In production, this would query the actual resource stores
        if resource_store:
            found = resource_store.list_resources(
                tenant_id=tenant_id,
                resource_type=category.value,
                project_id=project_id,
                created_before=cutoff,
                limit=max_per_category,
            )
            resources = found
        else:
            # No resource store - use mock data for testing
            # This simulates finding resources that match criteria
            resources = []

        result[category] = resources

    return result


def dry_run_retention(
    compliance_store: ComplianceStore,
    tenant_id: str,
    project_id: Optional[str] = None,
    resource_store: Optional[ResourceStore] = None,
    categories: Optional[List[ResourceCategory]] = None,
) -> PurgeResult:
    """
    Preview what would be deleted without actually deleting.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        project_id: Optional project ID
        resource_store: Optional resource store for actual resources
        categories: Optional list of categories to process

    Returns:
        PurgeResult with counts of what would be deleted
    """
    started_at = datetime.now(timezone.utc).isoformat()
    result = PurgeResult(
        mode="dry_run",
        tenant_id=tenant_id,
        project_id=project_id,
        started_at=started_at,
    )

    try:
        # Get effective policy
        policy = get_effective_policy(tenant_id, project_id, compliance_store)
        matcher = LegalHoldMatcher(compliance_store)

        # Process each category
        target_categories = categories or list(ResourceCategory)
        for category in target_categories:
            stats = _process_category_dry_run(
                compliance_store=compliance_store,
                resource_store=resource_store,
                tenant_id=tenant_id,
                project_id=project_id,
                category=category,
                policy=policy,
                matcher=matcher,
            )
            result.categories.append(stats)

            # Aggregate
            result.total_found += stats.total_found
            result.total_to_delete += stats.to_delete
            result.total_skipped_held += stats.skipped_held

        result.success = True

    except Exception as e:
        result.success = False
        result.error = str(e)

    result.finished_at = datetime.now(timezone.utc).isoformat()
    return result


def _process_category_dry_run(
    compliance_store: ComplianceStore,
    resource_store: Optional[ResourceStore],
    tenant_id: str,
    project_id: Optional[str],
    category: ResourceCategory,
    policy: RetentionPolicy,
    matcher: LegalHoldMatcher,
) -> PurgeStats:
    """Process a single category in dry run mode."""
    days = policy.get_category_days(category) or 0
    cutoff = compute_cutoff_date(category, policy)

    stats = PurgeStats(
        category=category.value,
        retention_days=days,
        cutoff_date=cutoff.isoformat() if cutoff else None,
    )

    if cutoff is None:
        # Indefinite retention
        return stats

    # Get resources that would be deleted
    if resource_store:
        resources = resource_store.list_resources(
            tenant_id=tenant_id,
            resource_type=category.value,
            project_id=project_id,
            created_before=cutoff,
            limit=1000,
        )
    else:
        # Mock: simulate finding some expired resources
        resources = []

    stats.total_found = len(resources)

    # Check which are held
    for resource in resources:
        resource_id = resource.get("id")
        is_held = matcher.is_held(
            tenant_id=tenant_id,
            resource_type=category.value,
            resource_id=resource_id,
            project_id=project_id,
        )
        if is_held:
            stats.skipped_held += 1
        else:
            stats.to_delete += 1

    return stats


def execute_retention(
    compliance_store: ComplianceStore,
    tenant_id: str,
    project_id: Optional[str] = None,
    resource_store: Optional[ResourceStore] = None,
    categories: Optional[List[ResourceCategory]] = None,
    max_deletions: int = MAX_DELETIONS_PER_RUN,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_delete: Optional[Callable[[str, str, str], None]] = None,
) -> PurgeResult:
    """
    Execute retention purge.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        project_id: Optional project ID
        resource_store: Optional resource store for actual resources
        categories: Optional list of categories to process
        max_deletions: Maximum resources to delete
        batch_size: Batch size for deletions
        on_delete: Optional callback(tenant_id, resource_type, resource_id)

    Returns:
        PurgeResult with counts of what was deleted
    """
    # Acquire advisory lock
    lock = _get_execution_lock(tenant_id, project_id)
    acquired = lock.acquire(blocking=False)

    if not acquired:
        return PurgeResult(
            mode="execute",
            tenant_id=tenant_id,
            project_id=project_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            success=False,
            error="Another purge is already running for this tenant/project",
        )

    try:
        return _execute_retention_locked(
            compliance_store=compliance_store,
            tenant_id=tenant_id,
            project_id=project_id,
            resource_store=resource_store,
            categories=categories,
            max_deletions=max_deletions,
            batch_size=batch_size,
            on_delete=on_delete,
        )
    finally:
        lock.release()


def _execute_retention_locked(
    compliance_store: ComplianceStore,
    tenant_id: str,
    project_id: Optional[str],
    resource_store: Optional[ResourceStore],
    categories: Optional[List[ResourceCategory]],
    max_deletions: int,
    batch_size: int,
    on_delete: Optional[Callable[[str, str, str], None]],
) -> PurgeResult:
    """Execute retention with lock already held."""
    started_at = datetime.now(timezone.utc).isoformat()

    # Create purge run record
    purge_run = compliance_store.create_purge_run(
        tenant_id=tenant_id,
        mode="execute",
        project_id=project_id,
    )

    result = PurgeResult(
        mode="execute",
        tenant_id=tenant_id,
        project_id=project_id,
        started_at=started_at,
        max_deletions=max_deletions,
    )

    try:
        # Get effective policy
        policy = get_effective_policy(tenant_id, project_id, compliance_store)
        matcher = LegalHoldMatcher(compliance_store)

        # Process each category
        target_categories = categories or list(ResourceCategory)
        total_deleted = 0

        for category in target_categories:
            if total_deleted >= max_deletions:
                result.hit_limit = True
                break

            remaining = max_deletions - total_deleted
            stats = _process_category_execute(
                compliance_store=compliance_store,
                resource_store=resource_store,
                tenant_id=tenant_id,
                project_id=project_id,
                category=category,
                policy=policy,
                matcher=matcher,
                max_deletions=remaining,
                batch_size=batch_size,
                on_delete=on_delete,
            )
            result.categories.append(stats)

            # Aggregate
            result.total_found += stats.total_found
            result.total_to_delete += stats.to_delete
            result.total_deleted += stats.deleted
            result.total_skipped_held += stats.skipped_held
            result.total_skipped_error += stats.skipped_error
            total_deleted += stats.deleted

        result.success = True

    except Exception as e:
        result.success = False
        result.error = str(e)

    result.finished_at = datetime.now(timezone.utc).isoformat()

    # Update purge run record
    compliance_store.finish_purge_run(
        run_id=purge_run["id"],
        summary=result.to_summary(),
        error_code="ERROR" if not result.success else None,
        error_detail=result.error,
    )

    return result


def _process_category_execute(
    compliance_store: ComplianceStore,
    resource_store: Optional[ResourceStore],
    tenant_id: str,
    project_id: Optional[str],
    category: ResourceCategory,
    policy: RetentionPolicy,
    matcher: LegalHoldMatcher,
    max_deletions: int,
    batch_size: int,
    on_delete: Optional[Callable[[str, str, str], None]],
) -> PurgeStats:
    """Process a single category in execute mode."""
    days = policy.get_category_days(category) or 0
    cutoff = compute_cutoff_date(category, policy)

    stats = PurgeStats(
        category=category.value,
        retention_days=days,
        cutoff_date=cutoff.isoformat() if cutoff else None,
    )

    if cutoff is None:
        # Indefinite retention
        return stats

    if resource_store is None:
        # No resource store - nothing to delete
        return stats

    # Get resources to delete
    resources = resource_store.list_resources(
        tenant_id=tenant_id,
        resource_type=category.value,
        project_id=project_id,
        created_before=cutoff,
        limit=max_deletions,
    )

    stats.total_found = len(resources)
    deleted_count = 0

    for resource in resources:
        if deleted_count >= max_deletions:
            break

        resource_id = resource.get("id")

        # Check legal hold
        is_held = matcher.is_held(
            tenant_id=tenant_id,
            resource_type=category.value,
            resource_id=resource_id,
            project_id=project_id,
        )

        if is_held:
            stats.skipped_held += 1
            continue

        stats.to_delete += 1

        # Delete the resource
        try:
            success = resource_store.delete_resource(
                tenant_id=tenant_id,
                resource_type=category.value,
                resource_id=resource_id,
            )
            if success:
                stats.deleted += 1
                deleted_count += 1
                if on_delete:
                    on_delete(tenant_id, category.value, resource_id)
            else:
                stats.skipped_error += 1
        except Exception:
            stats.skipped_error += 1

    return stats


def get_purge_status(compliance_store: ComplianceStore, run_id: str) -> Optional[Dict[str, Any]]:
    """
    Get status of a purge run.

    Args:
        compliance_store: ComplianceStore instance
        run_id: Purge run ID

    Returns:
        Purge run record or None
    """
    return compliance_store.get_purge_run(run_id)


def list_purge_history(
    compliance_store: ComplianceStore,
    tenant_id: str,
    project_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    List purge run history.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        project_id: Optional project ID
        limit: Maximum records to return

    Returns:
        List of purge run records
    """
    return compliance_store.list_purge_runs(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=limit,
    )
