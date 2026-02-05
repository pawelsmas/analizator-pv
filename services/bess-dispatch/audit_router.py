"""
Audit API router for BESS API (v3.0.0 PR4, v3.2.0 chain verification).

Endpoints:
- GET /audit - Query audit log entries
- GET /audit/verify - Verify audit chain integrity (v3.2.0)
- GET /audit/stats - Get audit chain statistics (v3.2.0)
- GET /audit/export/csv - Export audit log as CSV
- GET /audit/export/json - Export audit log as JSON
- GET /audit/export/zip - Export audit log as ZIP (CSV + JSON)

Requires admin role for all operations.
"""

import io
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from auth_config import AuthContext, Role
from auth_deps import require_role
from audit_store import get_audit_store


router = APIRouter(prefix="/audit", tags=["audit"])


# -------------------------------------------------------------------------
# Response models
# -------------------------------------------------------------------------

class AuditEntryResponse(BaseModel):
    """Single audit log entry."""
    id: str
    tenant_id: str
    created_at: str
    action: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    actor_role: Optional[str] = None
    auth_method: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditListResponse(BaseModel):
    """Response for listing audit entries."""
    items: List[AuditEntryResponse]
    total: int
    limit: int
    offset: int


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------

@router.get("", response_model=AuditListResponse)
def query_audit_log(
    action: Optional[str] = Query(None, description="Filter by action type"),
    actor_id: Optional[str] = Query(None, description="Filter by actor ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    from_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    to_date: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Query audit log entries for the current tenant.

    Requires admin role.
    """
    audit_store = get_audit_store()
    result = audit_store.query(
        tenant_id=auth.tenant_id,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    return AuditListResponse(
        items=[AuditEntryResponse(**item) for item in result["items"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


# -------------------------------------------------------------------------
# Chain Verification (v3.2.0)
# -------------------------------------------------------------------------

class ChainVerifyResponse(BaseModel):
    """Response for chain verification."""
    valid: bool
    entries_checked: int
    first_break_at: Optional[str] = None
    first_break_reason: Optional[str] = None


class ChainStatsResponse(BaseModel):
    """Response for chain statistics."""
    total_entries: int
    entries_with_hash: int
    first_entry_at: Optional[str] = None
    last_entry_at: Optional[str] = None


@router.get("/verify", response_model=ChainVerifyResponse)
def verify_audit_chain(
    limit: int = Query(10000, ge=1, le=100000, description="Max entries to verify"),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Verify the integrity of the audit chain (v3.2.0).

    Checks that each entry's prev_hash matches the previous entry's entry_hash,
    and that each entry_hash is correctly computed from the entry data.

    If tampering is detected, returns valid=false with details about the first break.

    Requires admin role.
    """
    audit_store = get_audit_store()
    result = audit_store.verify_chain(limit=limit)

    return ChainVerifyResponse(**result)


@router.get("/stats", response_model=ChainStatsResponse)
def get_audit_stats(
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get audit chain statistics (v3.2.0).

    Returns information about the audit log including total entries
    and how many have hash chain integrity.

    Requires admin role.
    """
    audit_store = get_audit_store()
    result = audit_store.get_chain_stats()

    return ChainStatsResponse(**result)


@router.get("/export/csv")
def export_audit_csv(
    from_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    to_date: Optional[str] = Query(None, description="End date (ISO format)"),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Export audit log as CSV.

    Requires admin role.
    """
    audit_store = get_audit_store()
    csv_content = audit_store.export_csv(
        tenant_id=auth.tenant_id,
        from_date=from_date,
        to_date=to_date,
    )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{auth.tenant_id}.csv"
        },
    )


@router.get("/export/json")
def export_audit_json(
    from_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    to_date: Optional[str] = Query(None, description="End date (ISO format)"),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Export audit log as JSON.

    Requires admin role.
    """
    audit_store = get_audit_store()
    json_content = audit_store.export_json(
        tenant_id=auth.tenant_id,
        from_date=from_date,
        to_date=to_date,
    )

    return Response(
        content=json_content,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{auth.tenant_id}.json"
        },
    )


@router.get("/export/zip")
def export_audit_zip(
    from_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    to_date: Optional[str] = Query(None, description="End date (ISO format)"),
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Export audit log as ZIP (contains CSV and JSON).

    Requires admin role.
    """
    audit_store = get_audit_store()

    csv_content = audit_store.export_csv(
        tenant_id=auth.tenant_id,
        from_date=from_date,
        to_date=to_date,
    )

    json_content = audit_store.export_json(
        tenant_id=auth.tenant_id,
        from_date=from_date,
        to_date=to_date,
    )

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("audit_log.csv", csv_content)
        zf.writestr("audit_log.json", json_content)

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{auth.tenant_id}.zip"
        },
    )
