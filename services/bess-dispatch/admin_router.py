"""
Admin API router for BESS API (v3.0.0 PR3, v3.1.0 users/invites/shares API, v3.2.0 key rotation).

Endpoints:
- GET /admin/api-keys - List API keys for tenant
- POST /admin/api-keys - Create new API key
- POST /admin/api-keys/{key_id}/rotate - Rotate API key (v3.2.0)
- DELETE /admin/api-keys/{key_id} - Revoke API key

User Management (v3.1.0):
- GET /admin/users - List users for tenant
- POST /admin/users - Create new user
- PATCH /admin/users/{user_id} - Update user (role, disabled)
- POST /admin/users/{user_id}/reset-password - Set new password

Invites (v3.1.0):
- GET /admin/invites - List invites for tenant
- POST /admin/invites - Create new invite
- DELETE /admin/invites/{invite_id} - Revoke invite

Shares (v3.1.0):
- GET /admin/shares - List shares for tenant
- POST /admin/shares - Create new share link
- DELETE /admin/shares/{share_id} - Revoke share link

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
    last_used_at: Optional[str] = None
    rotated_from: Optional[str] = None


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
            last_used_at=key.get("last_used_at"),
            rotated_from=key.get("rotated_from"),
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


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreateResponse)
def rotate_api_key(
    key_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Rotate an API key (v3.2.0).

    Creates a new API key with the same label and role, and revokes the old key.
    The new key's rotated_from field will reference the old key's ID.

    IMPORTANT: The new plaintext key is returned ONLY in this response.
    Store it securely - it cannot be retrieved later.

    Requires admin role.
    """
    auth_store = get_auth_store()
    new_key_info = auth_store.rotate_api_key(key_id, auth.tenant_id)

    if new_key_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "KEY_NOT_FOUND", "message": "API key not found or already revoked"},
        )

    return ApiKeyCreateResponse(
        id=new_key_info["id"],
        tenant_id=new_key_info["tenant_id"],
        label=new_key_info["label"],
        role=new_key_info["role"],
        created_at=new_key_info["created_at"],
        api_key=new_key_info["api_key"],
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


# -------------------------------------------------------------------------
# Invites (v3.1.0)
# -------------------------------------------------------------------------

class InviteResponse(BaseModel):
    """Invite response (excludes token)."""
    id: str
    tenant_id: str
    email: str
    role: str
    created_at: str
    expires_at: str
    accepted_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_by: str


class InviteListResponse(BaseModel):
    """Response for listing invites."""
    items: List[InviteResponse]
    total: int


class InviteCreateRequest(BaseModel):
    """Request to create a new invite."""
    email: str
    role: str = "editor"
    expires_hours: int = 72  # Default 72 hours expiry


class InviteCreateResponse(BaseModel):
    """Response after creating invite (includes plaintext token once)."""
    id: str
    tenant_id: str
    email: str
    role: str
    created_at: str
    expires_at: str
    created_by: str
    token: str  # Plaintext token - shown only once!


@router.get("/invites", response_model=InviteListResponse)
def list_invites(auth: AuthContext = Depends(require_role(Role.ADMIN))):
    """
    List invites for the current tenant.

    Shows all invites including accepted and revoked ones.

    Requires admin role.
    """
    auth_store = get_auth_store()
    invites = auth_store.list_invites(auth.tenant_id)

    items = [
        InviteResponse(
            id=invite["id"],
            tenant_id=invite["tenant_id"],
            email=invite["email"],
            role=invite["role"],
            created_at=invite["created_at"],
            expires_at=invite["expires_at"],
            accepted_at=invite["accepted_at"],
            revoked_at=invite["revoked_at"],
            created_by=invite["created_by"],
        )
        for invite in invites
    ]

    return InviteListResponse(items=items, total=len(items))


@router.post("/invites", response_model=InviteCreateResponse, status_code=status.HTTP_201_CREATED)
def create_invite(
    request: InviteCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new invite for a user to join the tenant.

    IMPORTANT: The invite token is returned ONLY in this response.
    Share it securely with the invitee - it cannot be retrieved later.

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

    # Check if user already exists in tenant
    if auth_store.email_exists_in_tenant(request.email, auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "USER_ALREADY_EXISTS", "message": f"User with email already exists: {request.email}"},
        )

    # Check if pending invite already exists
    if auth_store.pending_invite_exists(request.email, auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "INVITE_ALREADY_EXISTS", "message": f"Pending invite already exists for: {request.email}"},
        )

    # Validate expires_hours
    if request.expires_hours < 1 or request.expires_hours > 168:  # 1 hour to 1 week
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_EXPIRY", "message": "expires_hours must be between 1 and 168"},
        )

    invite = auth_store.create_invite(
        tenant_id=auth.tenant_id,
        email=request.email,
        role=role,
        created_by=auth.user_id,
        expires_hours=request.expires_hours,
    )

    return InviteCreateResponse(
        id=invite["id"],
        tenant_id=invite["tenant_id"],
        email=invite["email"],
        role=invite["role"],
        created_at=invite["created_at"],
        expires_at=invite["expires_at"],
        created_by=invite["created_by"],
        token=invite["token"],
    )


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Revoke an invite.

    The invite must belong to the authenticated user's tenant.
    Revoked invites cannot be used to create an account.

    Requires admin role.
    """
    auth_store = get_auth_store()
    revoked = auth_store.revoke_invite(invite_id, auth.tenant_id)

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "INVITE_NOT_FOUND", "message": "Invite not found or already used/revoked"},
        )

    return None


# -------------------------------------------------------------------------
# Shares (v3.1.0)
# -------------------------------------------------------------------------

class ShareResponse(BaseModel):
    """Share response (excludes token)."""
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    created_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_by: str
    label: Optional[str] = None


class ShareListResponse(BaseModel):
    """Response for listing shares."""
    items: List[ShareResponse]
    total: int


class ShareCreateRequest(BaseModel):
    """Request to create a new share link."""
    resource_type: str  # "run" or "report"
    resource_id: str
    label: Optional[str] = None
    expires_hours: Optional[int] = None  # None = never expires


class ShareCreateResponse(BaseModel):
    """Response after creating share (includes plaintext token once)."""
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    created_at: str
    expires_at: Optional[str] = None
    created_by: str
    label: Optional[str] = None
    token: str  # Plaintext token - shown only once!


@router.get("/shares", response_model=ShareListResponse)
def list_shares(
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    List shares for the current tenant.

    Can optionally filter by resource_type and resource_id.

    Requires admin role.
    """
    auth_store = get_auth_store()
    shares = auth_store.list_shares(auth.tenant_id, resource_type, resource_id)

    items = [
        ShareResponse(
            id=share["id"],
            tenant_id=share["tenant_id"],
            resource_type=share["resource_type"],
            resource_id=share["resource_id"],
            created_at=share["created_at"],
            expires_at=share["expires_at"],
            revoked_at=share["revoked_at"],
            created_by=share["created_by"],
            label=share["label"],
        )
        for share in shares
    ]

    return ShareListResponse(items=items, total=len(items))


@router.post("/shares", response_model=ShareCreateResponse, status_code=status.HTTP_201_CREATED)
def create_share(
    request: ShareCreateRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Create a new share link for a resource.

    IMPORTANT: The share token is returned ONLY in this response.
    Store it securely - it cannot be retrieved later.

    Requires admin role.
    """
    # Validate resource_type
    if request.resource_type not in ("run", "report"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_RESOURCE_TYPE", "message": "resource_type must be 'run' or 'report'"},
        )

    # Validate expires_hours if provided
    if request.expires_hours is not None:
        if request.expires_hours < 1 or request.expires_hours > 8760:  # 1 hour to 1 year
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_EXPIRY", "message": "expires_hours must be between 1 and 8760"},
            )

    auth_store = get_auth_store()

    share = auth_store.create_share(
        tenant_id=auth.tenant_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        created_by=auth.user_id,
        label=request.label,
        expires_hours=request.expires_hours,
    )

    return ShareCreateResponse(
        id=share["id"],
        tenant_id=share["tenant_id"],
        resource_type=share["resource_type"],
        resource_id=share["resource_id"],
        created_at=share["created_at"],
        expires_at=share["expires_at"],
        created_by=share["created_by"],
        label=share["label"],
        token=share["token"],
    )


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(
    share_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Revoke a share link.

    The share must belong to the authenticated user's tenant.
    Revoked shares cannot be used to access resources.

    Requires admin role.
    """
    auth_store = get_auth_store()
    revoked = auth_store.revoke_share(share_id, auth.tenant_id)

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SHARE_NOT_FOUND", "message": "Share not found or already revoked"},
        )

    return None
