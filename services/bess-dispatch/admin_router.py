"""
Admin API router for BESS API (v3.0.0 PR3, v3.1.0 users API).

Endpoints:
- GET /admin/api-keys - List API keys for tenant
- POST /admin/api-keys - Create new API key
- DELETE /admin/api-keys/{key_id} - Revoke API key

User Management (v3.1.0):
- GET /admin/users - List users for tenant
- POST /admin/users - Create new user
- PATCH /admin/users/{user_id} - Update user (role, disabled)
- POST /admin/users/{user_id}/reset-password - Set new password

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


# -------------------------------------------------------------------------
# User Management (v3.1.0)
# -------------------------------------------------------------------------

class UserResponse(BaseModel):
    """User response (excludes password_hash)."""
    id: str
    tenant_id: str
    email: str
    role: str
    created_at: str
    disabled: bool


class UserListResponse(BaseModel):
    """Response for listing users."""
    items: List[UserResponse]
    total: int


class UserCreateRequest(BaseModel):
    """Request to create a new user."""
    email: str
    role: str = "editor"
    password: Optional[str] = None  # If None, user must be invited


class UserUpdateRequest(BaseModel):
    """Request to update a user."""
    role: Optional[str] = None
    disabled: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    """Request to reset a user's password."""
    new_password: str


@router.get("/users", response_model=UserListResponse)
def list_users(auth: AuthContext = Depends(require_role(Role.ADMIN))):
    """
    List users for the current tenant.

    Requires admin role.
    """
    auth_store = get_auth_store()
    users = auth_store.list_users(auth.tenant_id)

    items = [
        UserResponse(
            id=user["id"],
            tenant_id=user["tenant_id"],
            email=user["email"],
            role=user["role"],
            created_at=user["created_at"],
            disabled=user["disabled"],
        )
        for user in users
    ]

    return UserListResponse(items=items, total=len(items))


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new user in the current tenant.

    If password is not provided, user needs to be invited separately.

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

    auth_store = get_auth_store()

    # Check email uniqueness in tenant
    if auth_store.email_exists_in_tenant(request.email, auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "EMAIL_ALREADY_EXISTS", "message": f"Email already exists: {request.email}"},
        )

    # If no password, generate a random one (user must use invite/reset)
    password = request.password or f"temp_{__import__('secrets').token_urlsafe(16)}"

    user = auth_store.create_user(
        tenant_id=auth.tenant_id,
        email=request.email,
        password=password,
        role=role,
    )

    return UserResponse(
        id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        role=user["role"],
        created_at=user["created_at"],
        disabled=user["disabled"],
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Update a user's role and/or disabled status.

    Cannot disable or demote the last admin in the tenant.

    Requires admin role.
    """
    auth_store = get_auth_store()

    # Get current user to check if it exists and check last-admin protection
    current_user = auth_store.get_user_by_id(user_id)
    if current_user is None or current_user["tenant_id"] != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found"},
        )

    # Validate role if provided
    if request.role is not None:
        try:
            Role(request.role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_ROLE", "message": f"Invalid role: {request.role}"},
            )

    # Last admin protection: cannot disable or demote last admin
    if current_user["role"] == Role.ADMIN.value and not current_user["disabled"]:
        # This user is an active admin
        is_demoting = request.role is not None and request.role != Role.ADMIN.value
        is_disabling = request.disabled is True

        if is_demoting or is_disabling:
            # Check if this is the last active admin
            admin_count = auth_store.count_active_admins(auth.tenant_id)
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "LAST_ADMIN_PROTECTED",
                        "message": "Cannot disable or demote the last admin in the tenant",
                    },
                )

    updated = auth_store.update_user(
        user_id=user_id,
        tenant_id=auth.tenant_id,
        role=request.role,
        disabled=request.disabled,
    )

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found"},
        )

    return UserResponse(
        id=updated["id"],
        tenant_id=updated["tenant_id"],
        email=updated["email"],
        role=updated["role"],
        created_at=updated["created_at"],
        disabled=updated["disabled"],
    )


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: str,
    request: ResetPasswordRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Reset a user's password.

    Sets a new password for the specified user.

    Requires admin role.
    """
    auth_store = get_auth_store()

    if len(request.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "PASSWORD_TOO_SHORT", "message": "Password must be at least 6 characters"},
        )

    success = auth_store.set_user_password(user_id, auth.tenant_id, request.new_password)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "USER_NOT_FOUND", "message": "User not found"},
        )

    return None
