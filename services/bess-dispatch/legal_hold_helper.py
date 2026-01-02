"""
Legal Hold Helper - SSoT for legal hold logic (v4.3.0 PR3).

Provides:
- LegalHoldMatcher - match resources against active holds
- check_resource_held() - check if resource is under hold
- purge_guard() - guard decorator/context for purge operations
- list_affected_resources() - find all resources affected by a hold
- HoldViolationError - exception for hold violations

Usage:
    from legal_hold_helper import (
        LegalHoldMatcher,
        check_resource_held,
        purge_guard,
        HoldViolationError,
    )

    matcher = LegalHoldMatcher(compliance_store)
    if matcher.is_held("tenant-1", "run", "run-123"):
        raise HoldViolationError("Resource is under legal hold")

    with purge_guard(compliance_store, tenant_id, resources):
        # Purge resources - will raise if any are held
        ...
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from pydantic import BaseModel, Field


class HoldScope(Enum):
    """Scope of a legal hold."""
    RESOURCE = "resource"   # Specific resource by ID
    PROJECT = "project"     # All resources in a project
    TENANT = "tenant"       # All resources in tenant


class HoldViolationError(Exception):
    """Raised when attempting to modify/delete a held resource."""

    def __init__(
        self,
        message: str,
        hold_ids: Optional[List[str]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ):
        self.hold_ids = hold_ids or []
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(message)


class HoldMatch(BaseModel):
    """Result of matching a resource against holds."""

    is_held: bool = Field(default=False, description="Whether resource is held")
    holds: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of matching holds",
    )
    hold_ids: List[str] = Field(
        default_factory=list,
        description="IDs of matching holds",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Reasons from matching holds",
    )
    scope: Optional[HoldScope] = Field(
        default=None,
        description="Most specific scope of matching hold",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_held": self.is_held,
            "hold_ids": self.hold_ids,
            "reasons": self.reasons,
            "scope": self.scope.value if self.scope else None,
        }


class LegalHoldMatcher:
    """
    Matcher for checking resources against active legal holds.

    Caches active holds per tenant to reduce database queries.
    """

    def __init__(self, compliance_store):
        """
        Initialize matcher.

        Args:
            compliance_store: ComplianceStore instance
        """
        self.compliance_store = compliance_store
        self._cache: Dict[str, Tuple[datetime, List[Dict[str, Any]]]] = {}
        self._cache_ttl_seconds = 60  # 1 minute cache

    def _get_active_holds(self, tenant_id: str) -> List[Dict[str, Any]]:
        """
        Get active holds for tenant (with caching).

        Args:
            tenant_id: Tenant ID

        Returns:
            List of active hold records
        """
        now = datetime.now(timezone.utc)

        # Check cache
        if tenant_id in self._cache:
            cache_time, holds = self._cache[tenant_id]
            age = (now - cache_time).total_seconds()
            if age < self._cache_ttl_seconds:
                return holds

        # Fetch from store
        holds = self.compliance_store.list_legal_holds(
            tenant_id=tenant_id,
            active_only=True,
        )

        # Update cache
        self._cache[tenant_id] = (now, holds)
        return holds

    def invalidate_cache(self, tenant_id: Optional[str] = None):
        """
        Invalidate cache.

        Args:
            tenant_id: Specific tenant to invalidate (None for all)
        """
        if tenant_id:
            self._cache.pop(tenant_id, None)
        else:
            self._cache.clear()

    def match(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> HoldMatch:
        """
        Match resource against active holds.

        Checks in order of specificity:
        1. Direct resource hold (most specific)
        2. Project-level hold
        3. Tenant-wide "all" hold (least specific)

        Args:
            tenant_id: Tenant ID
            resource_type: Type of resource (run/job/project/etc.)
            resource_id: Optional specific resource ID
            project_id: Optional project ID

        Returns:
            HoldMatch with matching holds
        """
        holds = self._get_active_holds(tenant_id)
        matching_holds = []
        scope = None

        for hold in holds:
            hold_type = hold.get("resource_type")
            hold_resource_id = hold.get("resource_id")
            hold_project_id = hold.get("project_id")

            matched = False

            # Check tenant-wide "all" hold
            if hold_type == "all":
                matched = True
                if scope is None:
                    scope = HoldScope.TENANT

            # Check project-level hold (any resource in project)
            elif hold_project_id and hold_project_id == project_id:
                if hold_type == resource_type or hold_type == "all":
                    matched = True
                    if scope != HoldScope.RESOURCE:
                        scope = HoldScope.PROJECT

            # Check direct resource hold
            elif hold_type == resource_type:
                if hold_resource_id:
                    # Specific resource ID
                    if hold_resource_id == resource_id:
                        matched = True
                        scope = HoldScope.RESOURCE
                elif hold_project_id == project_id:
                    # All resources of type in project
                    matched = True
                    if scope != HoldScope.RESOURCE:
                        scope = HoldScope.PROJECT

            # Check project hold blocking the project itself
            elif resource_type == "project" and hold_type == "project":
                if hold_resource_id == resource_id:
                    matched = True
                    scope = HoldScope.RESOURCE

            if matched:
                matching_holds.append(hold)

        return HoldMatch(
            is_held=len(matching_holds) > 0,
            holds=matching_holds,
            hold_ids=[h["id"] for h in matching_holds],
            reasons=[h.get("reason", "") for h in matching_holds],
            scope=scope,
        )

    def is_held(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> bool:
        """
        Quick check if resource is held.

        Args:
            tenant_id: Tenant ID
            resource_type: Type of resource
            resource_id: Optional specific resource ID
            project_id: Optional project ID

        Returns:
            True if resource is under any active hold
        """
        return self.match(tenant_id, resource_type, resource_id, project_id).is_held


def check_resource_held(
    compliance_store,
    tenant_id: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    project_id: Optional[str] = None,
    raise_on_held: bool = True,
) -> HoldMatch:
    """
    Check if resource is under legal hold.

    Convenience function that creates matcher and checks.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID
        resource_type: Type of resource
        resource_id: Optional specific resource ID
        project_id: Optional project ID
        raise_on_held: If True, raise HoldViolationError when held

    Returns:
        HoldMatch result

    Raises:
        HoldViolationError: If resource is held and raise_on_held=True
    """
    matcher = LegalHoldMatcher(compliance_store)
    result = matcher.match(tenant_id, resource_type, resource_id, project_id)

    if result.is_held and raise_on_held:
        reasons_str = "; ".join(result.reasons) if result.reasons else "Legal hold"
        raise HoldViolationError(
            f"Resource is under legal hold: {reasons_str}",
            hold_ids=result.hold_ids,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    return result


class ResourceRef(BaseModel):
    """Reference to a resource for purge operations."""

    tenant_id: str
    resource_type: str
    resource_id: Optional[str] = None
    project_id: Optional[str] = None


@contextmanager
def purge_guard(
    compliance_store,
    resources: List[ResourceRef],
    fail_fast: bool = True,
) -> Generator[Dict[str, List[ResourceRef]], None, None]:
    """
    Context manager that guards purge operations against legal holds.

    Checks all resources before allowing purge operations.

    Args:
        compliance_store: ComplianceStore instance
        resources: List of resources to check
        fail_fast: If True, raise on first held resource

    Yields:
        Dictionary with "allowed" and "blocked" resource lists

    Raises:
        HoldViolationError: If any resource is held and fail_fast=True

    Example:
        resources = [
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r1"),
            ResourceRef(tenant_id="t1", resource_type="run", resource_id="r2"),
        ]
        with purge_guard(store, resources) as result:
            for ref in result["allowed"]:
                purge_resource(ref)
    """
    matcher = LegalHoldMatcher(compliance_store)
    allowed: List[ResourceRef] = []
    blocked: List[ResourceRef] = []
    violations: List[Tuple[ResourceRef, HoldMatch]] = []

    for ref in resources:
        match = matcher.match(
            tenant_id=ref.tenant_id,
            resource_type=ref.resource_type,
            resource_id=ref.resource_id,
            project_id=ref.project_id,
        )

        if match.is_held:
            blocked.append(ref)
            violations.append((ref, match))

            if fail_fast:
                raise HoldViolationError(
                    f"Cannot purge {ref.resource_type}/{ref.resource_id}: under legal hold",
                    hold_ids=match.hold_ids,
                    resource_type=ref.resource_type,
                    resource_id=ref.resource_id,
                )
        else:
            allowed.append(ref)

    yield {"allowed": allowed, "blocked": blocked, "violations": violations}


def list_affected_resources(
    compliance_store,
    hold_id: str,
    resource_store=None,
) -> List[Dict[str, Any]]:
    """
    List resources affected by a specific legal hold.

    Args:
        compliance_store: ComplianceStore instance
        hold_id: Legal hold ID
        resource_store: Optional store for querying resources

    Returns:
        List of affected resource references
    """
    hold = compliance_store.get_legal_hold(hold_id)
    if not hold:
        return []

    affected = []
    tenant_id = hold["tenant_id"]
    resource_type = hold.get("resource_type")
    resource_id = hold.get("resource_id")
    project_id = hold.get("project_id")

    if resource_type == "all":
        # Tenant-wide hold - affects everything
        affected.append({
            "scope": "tenant",
            "tenant_id": tenant_id,
            "description": "All resources in tenant",
        })
    elif resource_id:
        # Specific resource hold
        affected.append({
            "scope": "resource",
            "tenant_id": tenant_id,
            "project_id": project_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "description": f"Specific {resource_type}: {resource_id}",
        })
    elif project_id:
        # Project-level hold for resource type
        affected.append({
            "scope": "project",
            "tenant_id": tenant_id,
            "project_id": project_id,
            "resource_type": resource_type,
            "description": f"All {resource_type}s in project {project_id}",
        })

    return affected


def get_hold_summary(compliance_store, tenant_id: str) -> Dict[str, Any]:
    """
    Get summary of legal holds for a tenant.

    Args:
        compliance_store: ComplianceStore instance
        tenant_id: Tenant ID

    Returns:
        Summary with counts and details
    """
    active_holds = compliance_store.list_legal_holds(
        tenant_id=tenant_id,
        active_only=True,
    )

    all_holds = compliance_store.list_legal_holds(
        tenant_id=tenant_id,
        active_only=False,
    )

    # Categorize holds
    by_scope = {"resource": 0, "project": 0, "tenant": 0}
    by_type = {}

    for hold in active_holds:
        resource_type = hold.get("resource_type", "unknown")
        by_type[resource_type] = by_type.get(resource_type, 0) + 1

        if resource_type == "all":
            by_scope["tenant"] += 1
        elif hold.get("resource_id"):
            by_scope["resource"] += 1
        elif hold.get("project_id"):
            by_scope["project"] += 1

    return {
        "active_count": len(active_holds),
        "total_count": len(all_holds),
        "released_count": len(all_holds) - len(active_holds),
        "by_scope": by_scope,
        "by_type": by_type,
        "holds": active_holds[:10],  # First 10 for preview
    }
