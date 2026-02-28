"""
Quota Enforcement Middleware (v4.0.0).

Enforces quota limits before allowing operations:
- Returns 429 QUOTA_EXCEEDED when quota is exceeded
- Includes Retry-After header with seconds until reset
- Provides check_and_enforce() for pre-flight checks

Usage in routes:
    from quota_enforcement import check_and_enforce, QuotaExceededError

    @router.post("/jobs")
    async def create_job(auth: AuthContext = Depends(get_auth_context)):
        check_and_enforce(auth.tenant_id, auth.project_id, "jobs_per_day")
        # ... proceed with job creation
"""

import os
from typing import Optional

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from quota_engine import check_quota, get_seconds_until_reset


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Error code for quota exceeded responses
QUOTA_EXCEEDED_CODE = "QUOTA_EXCEEDED"


# -----------------------------------------------------------------------------
# Exception
# -----------------------------------------------------------------------------

class QuotaExceededError(HTTPException):
    """
    Exception raised when quota is exceeded.

    Includes:
    - 429 status code
    - Retry-After header
    - Structured error response with quota details
    """

    def __init__(
        self,
        quota_name: str,
        limit: int,
        used: int,
        retry_after: int,
        message: Optional[str] = None,
    ):
        self.quota_name = quota_name
        self.limit = limit
        self.used = used
        self.retry_after = retry_after

        if message is None:
            message = f"Quota exceeded for '{quota_name}': {used}/{limit} used. Resets in {retry_after} seconds."

        detail = {
            "code": QUOTA_EXCEEDED_CODE,
            "message": message,
            "quota_name": quota_name,
            "limit": limit,
            "used": used,
            "retry_after_seconds": retry_after,
        }

        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


# -----------------------------------------------------------------------------
# Enforcement Functions
# -----------------------------------------------------------------------------

def check_and_enforce(
    tenant_id: str,
    project_id: str,
    quota_name: str,
    increment: int = 1,
) -> dict:
    """
    Check quota and raise QuotaExceededError if exceeded.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        quota_name: Name of quota to check (e.g., 'jobs_per_day')
        increment: Amount to add (for batch operations)

    Returns:
        Dict with quota info if allowed

    Raises:
        QuotaExceededError: If quota would be exceeded
    """
    result = check_quota(tenant_id, project_id, quota_name, increment)

    if not result["allowed"]:
        retry_after = get_seconds_until_reset()
        raise QuotaExceededError(
            quota_name=quota_name,
            limit=result["limit"],
            used=result["used"],
            retry_after=retry_after,
        )

    return result


def enforce_jobs_quota(tenant_id: str, project_id: str, count: int = 1) -> dict:
    """
    Convenience function to check jobs_per_day quota.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        count: Number of jobs to enqueue

    Returns:
        Dict with quota info if allowed

    Raises:
        QuotaExceededError: If jobs quota would be exceeded
    """
    return check_and_enforce(tenant_id, project_id, "jobs_per_day", count)


def enforce_reports_quota(tenant_id: str, project_id: str, count: int = 1) -> dict:
    """
    Convenience function to check reports_per_day quota.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        count: Number of reports to generate

    Returns:
        Dict with quota info if allowed

    Raises:
        QuotaExceededError: If reports quota would be exceeded
    """
    return check_and_enforce(tenant_id, project_id, "reports_per_day", count)


def enforce_shares_quota(tenant_id: str, project_id: str, count: int = 1) -> dict:
    """
    Convenience function to check shares_total quota.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        count: Number of shares to create

    Returns:
        Dict with quota info if allowed

    Raises:
        QuotaExceededError: If shares quota would be exceeded
    """
    return check_and_enforce(tenant_id, project_id, "shares_total", count)


def enforce_storage_quota(tenant_id: str, project_id: str, bytes_to_add: int) -> dict:
    """
    Convenience function to check storage_mb quota.

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        bytes_to_add: Bytes of storage to add

    Returns:
        Dict with quota info if allowed

    Raises:
        QuotaExceededError: If storage quota would be exceeded
    """
    # Convert bytes to MB for comparison
    mb_to_add = max(1, bytes_to_add // (1024 * 1024))
    return check_and_enforce(tenant_id, project_id, "storage_mb", mb_to_add)


# -----------------------------------------------------------------------------
# Exception Handler
# -----------------------------------------------------------------------------

async def quota_exceeded_handler(request, exc: QuotaExceededError) -> JSONResponse:
    """
    FastAPI exception handler for QuotaExceededError.

    Returns JSON response with:
    - 429 status code
    - Retry-After header
    - Structured error body

    Usage in main.py:
        from quota_enforcement import QuotaExceededError, quota_exceeded_handler
        app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)
    """
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=exc.detail,
        headers={"Retry-After": str(exc.retry_after)},
    )


# -----------------------------------------------------------------------------
# Dependency for FastAPI
# -----------------------------------------------------------------------------

class QuotaEnforcer:
    """
    FastAPI dependency for enforcing quotas.

    Usage:
        from quota_enforcement import QuotaEnforcer

        @router.post("/jobs")
        async def create_job(
            auth: AuthContext = Depends(get_auth_context),
            _: None = Depends(QuotaEnforcer("jobs_per_day")),
        ):
            # Quota already checked
            ...
    """

    def __init__(self, quota_name: str, increment: int = 1):
        self.quota_name = quota_name
        self.increment = increment

    async def __call__(self, auth=None, tenant_id: str = None, project_id: str = None):
        """
        Check quota using auth context or explicit IDs.
        """
        if auth is not None:
            tenant_id = auth.tenant_id
            project_id = auth.project_id

        if tenant_id is None or project_id is None:
            raise ValueError("tenant_id and project_id required for quota enforcement")

        return check_and_enforce(tenant_id, project_id, self.quota_name, self.increment)
