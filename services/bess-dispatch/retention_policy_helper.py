"""
Retention Policy Helper - SSoT for retention policy logic (v4.3.0 PR2).

Provides:
- RetentionPolicy Pydantic model
- merge_policies() - merge tenant default with project override
- validate_policy() - validation of policy structure
- get_effective_policy() - compute effective policy for a project
- compute_cutoff_date() - calculate cutoff for a resource category

Usage:
    from retention_policy_helper import (
        RetentionPolicy,
        merge_policies,
        get_effective_policy,
        compute_cutoff_date,
    )

    tenant_policy = RetentionPolicy(runs_days=365)
    project_override = RetentionPolicy(runs_days=90)
    effective = merge_policies(tenant_policy, project_override)
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ResourceCategory(Enum):
    """Categories of resources that can be retained/purged."""
    RUNS = "runs"
    JOBS = "jobs"
    REPORTS = "reports"
    AUDIT_LOGS = "audit_logs"
    EXPORTS = "exports"


# Default retention periods (in days)
DEFAULT_RETENTION_DAYS = {
    ResourceCategory.RUNS: 365,        # 1 year
    ResourceCategory.JOBS: 90,         # 3 months
    ResourceCategory.REPORTS: 365,     # 1 year
    ResourceCategory.AUDIT_LOGS: 730,  # 2 years (compliance requirement)
    ResourceCategory.EXPORTS: 30,      # 1 month
}

# Minimum retention periods (cannot go below)
MIN_RETENTION_DAYS = {
    ResourceCategory.RUNS: 7,
    ResourceCategory.JOBS: 7,
    ResourceCategory.REPORTS: 7,
    ResourceCategory.AUDIT_LOGS: 90,   # Compliance minimum
    ResourceCategory.EXPORTS: 1,
}

# Maximum retention periods (cannot exceed)
MAX_RETENTION_DAYS = {
    ResourceCategory.RUNS: 3650,       # 10 years
    ResourceCategory.JOBS: 3650,
    ResourceCategory.REPORTS: 3650,
    ResourceCategory.AUDIT_LOGS: 3650,
    ResourceCategory.EXPORTS: 365,
}


class RetentionPolicy(BaseModel):
    """
    Retention policy configuration.

    All fields are optional - only specified fields will be merged/applied.
    Days=0 means "never delete" (indefinite retention).
    Days=-1 means "use default/inherited value".
    """

    runs_days: Optional[int] = Field(
        default=None,
        description="Retention period for sizing runs (days). 0=indefinite, -1=inherit.",
    )
    jobs_days: Optional[int] = Field(
        default=None,
        description="Retention period for batch jobs (days). 0=indefinite, -1=inherit.",
    )
    reports_days: Optional[int] = Field(
        default=None,
        description="Retention period for reports (days). 0=indefinite, -1=inherit.",
    )
    audit_logs_days: Optional[int] = Field(
        default=None,
        description="Retention period for audit logs (days). 0=indefinite, -1=inherit.",
    )
    exports_days: Optional[int] = Field(
        default=None,
        description="Retention period for export artifacts (days). 0=indefinite, -1=inherit.",
    )

    @field_validator("runs_days", "jobs_days", "reports_days", "audit_logs_days", "exports_days")
    @classmethod
    def validate_days(cls, v: Optional[int]) -> Optional[int]:
        """Validate days value is within acceptable range."""
        if v is None:
            return None
        if v < -1:
            raise ValueError("Days must be >= -1 (-1=inherit, 0=indefinite, >0=days)")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with only non-None values."""
        result = {}
        if self.runs_days is not None:
            result["runs_days"] = self.runs_days
        if self.jobs_days is not None:
            result["jobs_days"] = self.jobs_days
        if self.reports_days is not None:
            result["reports_days"] = self.reports_days
        if self.audit_logs_days is not None:
            result["audit_logs_days"] = self.audit_logs_days
        if self.exports_days is not None:
            result["exports_days"] = self.exports_days
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetentionPolicy":
        """Create from dictionary."""
        return cls(
            runs_days=data.get("runs_days"),
            jobs_days=data.get("jobs_days"),
            reports_days=data.get("reports_days"),
            audit_logs_days=data.get("audit_logs_days"),
            exports_days=data.get("exports_days"),
        )

    def get_category_days(self, category: ResourceCategory) -> Optional[int]:
        """Get retention days for a specific category."""
        mapping = {
            ResourceCategory.RUNS: self.runs_days,
            ResourceCategory.JOBS: self.jobs_days,
            ResourceCategory.REPORTS: self.reports_days,
            ResourceCategory.AUDIT_LOGS: self.audit_logs_days,
            ResourceCategory.EXPORTS: self.exports_days,
        }
        return mapping.get(category)


class PolicyValidationError(Exception):
    """Raised when policy validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Policy validation failed: {', '.join(errors)}")


def validate_policy(policy: RetentionPolicy) -> List[str]:
    """
    Validate a retention policy.

    Returns list of validation errors (empty if valid).
    Checks:
    - Values within min/max bounds
    - Audit logs minimum compliance requirement
    """
    errors = []

    # Check each category
    for category in ResourceCategory:
        days = policy.get_category_days(category)
        if days is None or days == -1:
            continue  # Not specified or inherit

        if days == 0:
            continue  # Indefinite is always valid

        min_days = MIN_RETENTION_DAYS[category]
        max_days = MAX_RETENTION_DAYS[category]

        if days < min_days:
            errors.append(
                f"{category.value}_days ({days}) below minimum ({min_days})"
            )
        if days > max_days:
            errors.append(
                f"{category.value}_days ({days}) exceeds maximum ({max_days})"
            )

    return errors


def validate_policy_strict(policy: RetentionPolicy) -> None:
    """
    Validate policy and raise if invalid.

    Raises:
        PolicyValidationError: If validation fails
    """
    errors = validate_policy(policy)
    if errors:
        raise PolicyValidationError(errors)


def merge_policies(
    tenant_default: Optional[RetentionPolicy],
    project_override: Optional[RetentionPolicy],
) -> RetentionPolicy:
    """
    Merge tenant default with project override.

    Priority (highest to lowest):
    1. Project override value (if not None and not -1)
    2. Tenant default value (if not None and not -1)
    3. System default

    Args:
        tenant_default: Tenant-level policy (may be None)
        project_override: Project-level override (may be None)

    Returns:
        Merged effective policy
    """
    result = {}

    for category in ResourceCategory:
        field_name = f"{category.value}_days"
        system_default = DEFAULT_RETENTION_DAYS[category]

        # Get values from each level
        project_value = None
        tenant_value = None

        if project_override:
            project_value = project_override.get_category_days(category)
        if tenant_default:
            tenant_value = tenant_default.get_category_days(category)

        # Apply priority rules
        effective_value = system_default

        # Tenant default overrides system default (if not -1/None)
        if tenant_value is not None and tenant_value != -1:
            effective_value = tenant_value

        # Project override takes precedence (if not -1/None)
        if project_value is not None and project_value != -1:
            effective_value = project_value

        result[field_name] = effective_value

    return RetentionPolicy(**result)


def get_effective_policy(
    tenant_id: str,
    project_id: Optional[str],
    compliance_store,
) -> RetentionPolicy:
    """
    Get effective retention policy for a project.

    Loads policies from store and merges them.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID (None for tenant-level effective)
        compliance_store: ComplianceStore instance

    Returns:
        Effective merged policy
    """
    # Get tenant default
    tenant_policy_record = compliance_store.get_retention_policy(
        tenant_id, project_id=None
    )
    tenant_policy = None
    if tenant_policy_record and tenant_policy_record.get("enabled"):
        tenant_policy = RetentionPolicy.from_dict(
            tenant_policy_record.get("policy_json", {})
        )

    # Get project override if applicable
    project_policy = None
    if project_id:
        project_policy_record = compliance_store.get_retention_policy(
            tenant_id, project_id=project_id
        )
        if project_policy_record and project_policy_record.get("enabled"):
            project_policy = RetentionPolicy.from_dict(
                project_policy_record.get("policy_json", {})
            )

    return merge_policies(tenant_policy, project_policy)


def compute_cutoff_date(
    category: ResourceCategory,
    policy: RetentionPolicy,
    reference_date: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Compute cutoff date for a resource category.

    Resources created before the cutoff date are eligible for purge.

    Args:
        category: Resource category
        policy: Effective retention policy
        reference_date: Reference date (default: now)

    Returns:
        Cutoff datetime (UTC), or None if indefinite retention (days=0)
    """
    days = policy.get_category_days(category)

    if days is None:
        days = DEFAULT_RETENTION_DAYS[category]

    if days == 0:
        return None  # Indefinite retention

    if reference_date is None:
        reference_date = datetime.now(timezone.utc)

    return reference_date - timedelta(days=days)


def is_resource_expired(
    created_at: datetime,
    category: ResourceCategory,
    policy: RetentionPolicy,
    reference_date: Optional[datetime] = None,
) -> bool:
    """
    Check if a resource is expired according to policy.

    Args:
        created_at: Resource creation datetime
        category: Resource category
        policy: Effective retention policy
        reference_date: Reference date (default: now)

    Returns:
        True if resource is expired and eligible for purge
    """
    cutoff = compute_cutoff_date(category, policy, reference_date)

    if cutoff is None:
        return False  # Indefinite retention

    # Ensure created_at is timezone-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return created_at < cutoff


def format_retention_period(days: int) -> str:
    """
    Format retention period for display.

    Args:
        days: Number of days (0=indefinite)

    Returns:
        Human-readable string
    """
    if days == 0:
        return "Indefinite"
    if days == 1:
        return "1 day"
    if days < 30:
        return f"{days} days"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''}"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''}"


def summarize_policy(policy: RetentionPolicy) -> Dict[str, str]:
    """
    Summarize policy for display.

    Returns:
        Dictionary with human-readable retention periods
    """
    result = {}
    for category in ResourceCategory:
        days = policy.get_category_days(category)
        if days is None:
            days = DEFAULT_RETENTION_DAYS[category]
        result[category.value] = format_retention_period(days)
    return result
