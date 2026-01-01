"""
Admin API router for BESS API (v3.0.0 PR3).

Endpoints:
- GET /admin/api-keys - List API keys for tenant
- POST /admin/api-keys - Create new API key
- DELETE /admin/api-keys/{key_id} - Revoke API key

Requires admin role for all operations.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth_config import AuthContext, Role
from auth_deps import require_role
from auth_store import get_auth_store


router = APIRouter(prefix="/admin", tags=["admin"])


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class ApiKeyResponse(BaseModel):
    """API key response (excludes sensitive data)."""
    id: str
    tenant_id: str
    label: str
    role: str
    created_at: str
    revoked_at: Optional[str] = None


class ApiKeyCreateRequest(BaseModel):
    """Request to create a new API key."""
    label: str
    role: str = "service"


class ApiKeyCreateResponse(BaseModel):
    """Response after creating API key (includes plaintext key once)."""
    id: str
    tenant_id: str
    label: str
    role: str
    created_at: str
    api_key: str  # Plaintext key - shown only once!


class ApiKeyListResponse(BaseModel):
    """Response for listing API keys."""
    items: List[ApiKeyResponse]
    total: int


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------

@router.get("/api-keys", response_model=ApiKeyListResponse)
def list_api_keys(auth: AuthContext = Depends(require_role(Role.ADMIN))):
    """
    List API keys for the current tenant.

    Only shows keys for the authenticated user's tenant.
    Requires admin role.
    """
    auth_store = get_auth_store()
    keys = auth_store.list_api_keys(auth.tenant_id)

    items = [
        ApiKeyResponse(
            id=key["id"],
            tenant_id=key["tenant_id"],
            label=key["label"],
            role=key["role"],
            created_at=key["created_at"],
            revoked_at=key["revoked_at"],
        )
        for key in keys
    ]

    return ApiKeyListResponse(items=items, total=len(items))


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    request: ApiKeyCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new API key for the current tenant.

    IMPORTANT: The plaintext key is returned ONLY in this response.
    Store it securely - it cannot be retrieved later.

    Requires admin role.
    """
    # Validate role
    try:
        role = Role(request.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_ROLE", "message": f"Invalid role: {request.role}"},
        )

    # Admin cannot create admin API keys (security)
    if role == Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "ADMIN_KEY_FORBIDDEN", "message": "Cannot create admin API keys"},
        )

    auth_store = get_auth_store()
    key_info = auth_store.create_api_key(
        tenant_id=auth.tenant_id,
        label=request.label,
        role=role,
    )

    return ApiKeyCreateResponse(
        id=key_info["id"],
        tenant_id=key_info["tenant_id"],
        label=key_info["label"],
        role=key_info["role"],
        created_at=key_info["created_at"],
        api_key=key_info["api_key"],
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Revoke an API key.

    The key must belong to the authenticated user's tenant.
    Revoked keys cannot be used for authentication.

    Requires admin role.
    """
    auth_store = get_auth_store()
    revoked = auth_store.revoke_api_key(key_id, auth.tenant_id)

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "KEY_NOT_FOUND", "message": "API key not found"},
        )

    # Return 204 No Content on success
    return None
