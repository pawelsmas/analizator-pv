"""
Shared access router for public share links (v3.8.0).

Endpoints for accessing resources via share tokens without authentication.
Enforces password protection, single-use, and max access limits.

Headers:
- X-Share-Token: Share token (required)
- X-Share-Password: Share password (required if share has requires_password=true)
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status

from auth_store import get_auth_store
from audit_store import log_audit

router = APIRouter(prefix="/shared", tags=["shared"])


def _get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from request (handles proxies)."""
    # Check X-Forwarded-For first (reverse proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    # Fall back to direct client
    if request.client:
        return request.client.host
    return None


def _log_share_access(
    auth_store,
    share_id: str,
    tenant_id: str,
    access_result: str,
    request: Request,
):
    """Log share access attempt with IP and user agent (v3.8.0 PR3)."""
    ip_address = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    auth_store.log_share_access(
        share_id=share_id,
        tenant_id=tenant_id,
        access_result=access_result,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# =============================================================================
# Shared Runs Access (v3.8.0)
# =============================================================================


@router.get("/runs/{run_id}")
def get_shared_run(
    run_id: str,
    request: Request,
    x_share_token: str = Header(..., alias="X-Share-Token"),
    x_share_password: Optional[str] = Header(None, alias="X-Share-Password"),
) -> Dict[str, Any]:
    """
    Access a shared run via share token.

    Headers:
    - X-Share-Token: Required. The share token.
    - X-Share-Password: Required if share has requires_password=true.

    Returns the run data if access is valid.

    Error responses (v3.8.0):
    - 401 SHARE_NOT_FOUND: Token not found or revoked
    - 401 SHARE_EXPIRED: Share has expired
    - 401 SHARE_PASSWORD_REQUIRED: Password required but not provided
    - 401 SHARE_PASSWORD_INVALID: Incorrect password
    - 409 SHARE_MAX_ACCESS_EXCEEDED: Max downloads reached
    - 409 SHARE_ALREADY_USED: Single-use share already used
    - 404 RUN_NOT_FOUND: Run does not exist
    - 403 RESOURCE_MISMATCH: Share is for a different resource
    """
    auth_store = get_auth_store()

    # Verify share access with all v3.8.0 checks
    result = auth_store.verify_share_access(
        token=x_share_token,
        password=x_share_password,
    )

    if not result["valid"]:
        error_code = result["error_code"]
        share_for_log = result.get("share")

        # Log to access logs table (v3.8.0 PR3) if we have share info
        if share_for_log:
            _log_share_access(
                auth_store,
                share_id=share_for_log["id"],
                tenant_id=share_for_log["tenant_id"],
                access_result=f"denied_{error_code.lower()}",
                request=request,
            )

        # Log failed access attempt for audit
        log_audit(
            tenant_id=share_for_log["tenant_id"] if share_for_log else "unknown",
            action="share_access_denied",
            actor_id="anonymous",
            actor_email=None,
            actor_role=None,
            auth_method="share_token",
            resource_type="run",
            resource_id=run_id,
            details={
                "error_code": error_code,
                "share_id": share_for_log["id"] if share_for_log else None,
            },
        )

        # Map error codes to HTTP status codes
        if error_code in ("SHARE_NOT_FOUND", "SHARE_EXPIRED", "SHARE_PASSWORD_REQUIRED", "SHARE_PASSWORD_INVALID"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": error_code, "message": _get_error_message(error_code)},
            )
        if error_code in ("SHARE_MAX_ACCESS_EXCEEDED", "SHARE_ALREADY_USED"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": error_code, "message": _get_error_message(error_code)},
            )
        # Fallback for unknown errors
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": error_code, "message": "Access denied"},
        )

    share = result["share"]

    # Check resource type matches
    if share["resource_type"] != "run":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "RESOURCE_MISMATCH", "message": "Share is not for a run resource"},
        )

    # Check resource ID matches
    if share["resource_id"] != run_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "RESOURCE_MISMATCH", "message": "Share is for a different run"},
        )

    # Get the run from runstore
    from runstore import get_runstore
    runstore = get_runstore()
    run = runstore.get(run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "RUN_NOT_FOUND", "message": "Run not found"},
        )

    # Record the access (increment counter, auto-revoke if single-use)
    access_result = auth_store.record_share_access(share["id"])

    # Log to access logs table (v3.8.0 PR3)
    _log_share_access(
        auth_store,
        share_id=share["id"],
        tenant_id=share["tenant_id"],
        access_result="success",
        request=request,
    )

    # Log successful access for audit
    log_audit(
        tenant_id=share["tenant_id"],
        action="share_accessed",
        actor_id="anonymous",
        actor_email=None,
        actor_role=None,
        auth_method="share_token",
        resource_type="run",
        resource_id=run_id,
        details={
            "share_id": share["id"],
            "access_count": access_result["access_count"],
            "auto_revoked": access_result["auto_revoked"],
            "requires_password": share.get("requires_password", False),
        },
    )

    return run


@router.get("/runs/{run_id}/summary")
def get_shared_run_summary(
    run_id: str,
    request: Request,
    x_share_token: str = Header(..., alias="X-Share-Token"),
    x_share_password: Optional[str] = Header(None, alias="X-Share-Password"),
) -> Dict[str, Any]:
    """
    Access a shared run summary via share token.

    Same access rules as /shared/runs/{run_id} but returns only summary data.
    Increments access counter.

    Headers:
    - X-Share-Token: Required. The share token.
    - X-Share-Password: Required if share has requires_password=true.
    """
    auth_store = get_auth_store()

    # Verify share access
    result = auth_store.verify_share_access(
        token=x_share_token,
        password=x_share_password,
    )

    if not result["valid"]:
        error_code = result["error_code"]
        share_for_log = result.get("share")

        # Log to access logs table (v3.8.0 PR3) if we have share info
        if share_for_log:
            _log_share_access(
                auth_store,
                share_id=share_for_log["id"],
                tenant_id=share_for_log["tenant_id"],
                access_result=f"denied_{error_code.lower()}",
                request=request,
            )

        if error_code in ("SHARE_NOT_FOUND", "SHARE_EXPIRED", "SHARE_PASSWORD_REQUIRED", "SHARE_PASSWORD_INVALID"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": error_code, "message": _get_error_message(error_code)},
            )
        if error_code in ("SHARE_MAX_ACCESS_EXCEEDED", "SHARE_ALREADY_USED"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": error_code, "message": _get_error_message(error_code)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": error_code, "message": "Access denied"},
        )

    share = result["share"]

    # Validate resource
    if share["resource_type"] != "run":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "RESOURCE_MISMATCH", "message": "Share is not for a run resource"},
        )

    if share["resource_id"] != run_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "RESOURCE_MISMATCH", "message": "Share is for a different run"},
        )

    # Get run summary
    from runstore import get_runstore
    runstore = get_runstore()
    run = runstore.get(run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "RUN_NOT_FOUND", "message": "Run not found"},
        )

    # Record access
    auth_store.record_share_access(share["id"])

    # Log to access logs table (v3.8.0 PR3)
    _log_share_access(
        auth_store,
        share_id=share["id"],
        tenant_id=share["tenant_id"],
        access_result="success",
        request=request,
    )

    # Return only summary fields
    summary = {
        "id": run.get("id"),
        "created_at": run.get("created_at"),
        "request_type": run.get("request", {}).get("mode"),
        "status": run.get("status"),
    }

    # Include KPI summary if available
    if "recommended" in run:
        rec = run["recommended"]
        summary["recommended"] = {
            "name": rec.get("name"),
            "energy_kwh": rec.get("energy_kwh"),
            "power_kw": rec.get("power_kw"),
            "duration_hours": rec.get("duration_hours"),
            "npv_pln": rec.get("npv_pln"),
            "payback_years": rec.get("payback_years"),
        }

    return summary


def _get_error_message(error_code: str) -> str:
    """Get human-readable error message for error code."""
    messages = {
        "SHARE_NOT_FOUND": "Share not found or has been revoked",
        "SHARE_EXPIRED": "Share link has expired",
        "SHARE_PASSWORD_REQUIRED": "Password required to access this share",
        "SHARE_PASSWORD_INVALID": "Incorrect password",
        "SHARE_MAX_ACCESS_EXCEEDED": "Maximum download limit reached",
        "SHARE_ALREADY_USED": "This single-use share has already been used",
    }
    return messages.get(error_code, "Access denied")
