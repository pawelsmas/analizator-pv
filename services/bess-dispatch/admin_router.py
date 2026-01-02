"""
Admin API router for BESS API (v3.0.0 PR3, v3.1.0 users/invites/shares API).

Endpoints:
- GET /admin/api-keys - List API keys for tenant
- POST /admin/api-keys - Create new API key
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
from audit_store import log_audit


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
    """Share response (excludes token and password_hash)."""
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    created_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_by: str
    label: Optional[str] = None
    project_id: Optional[str] = None
    # v3.8.0 fields
    requires_password: bool = False
    single_use: bool = False
    max_access_count: Optional[int] = None
    access_count: int = 0
    last_access_at: Optional[str] = None
    token_version: int = 1


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
    project_id: Optional[str] = None  # v3.7.0: optional project for policy enforcement
    # v3.8.0 fields
    requires_password: bool = False
    password: Optional[str] = None  # Plaintext, only used during creation
    single_use: bool = False
    max_access_count: Optional[int] = None


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
    project_id: Optional[str] = None
    # v3.8.0 fields
    requires_password: bool = False
    single_use: bool = False
    max_access_count: Optional[int] = None
    access_count: int = 0
    token_version: int = 1
    token: str  # Plaintext token - shown only once!


@router.get("/shares", response_model=ShareListResponse)
def list_shares(
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    project_id: Optional[str] = None,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    List shares for the current tenant.

    Can optionally filter by resource_type, resource_id, and project_id.

    Requires admin role.
    """
    auth_store = get_auth_store()
    shares = auth_store.list_shares(
        auth.tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
    )

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
            project_id=share.get("project_id"),
            # v3.8.0 fields
            requires_password=share.get("requires_password", False),
            single_use=share.get("single_use", False),
            max_access_count=share.get("max_access_count"),
            access_count=share.get("access_count", 0),
            last_access_at=share.get("last_access_at"),
            token_version=share.get("token_version", 1),
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

    If project_id is provided, project share policies are enforced:
    - allow_public_shares must be True or request is rejected
    - share_max_expiry_hours caps the requested expires_hours

    v3.8.0 additions:
    - requires_password: If true, password must be provided for access
    - password: Plaintext password (min 10 chars) - stored hashed
    - single_use: If true, share is auto-revoked after first access
    - max_access_count: Maximum number of times share can be accessed

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

    # Validate max_access_count if provided (v3.8.0)
    if request.max_access_count is not None:
        if request.max_access_count < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "INVALID_MAX_ACCESS_COUNT", "message": "max_access_count must be at least 1"},
            )

    auth_store = get_auth_store()

    try:
        share = auth_store.create_share(
            tenant_id=auth.tenant_id,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            created_by=auth.user_id,
            label=request.label,
            expires_hours=request.expires_hours,
            project_id=request.project_id,
            # v3.8.0 parameters
            requires_password=request.requires_password,
            password=request.password,
            single_use=request.single_use,
            max_access_count=request.max_access_count,
        )
    except ValueError as e:
        error_msg = str(e)
        if "PUBLIC_SHARES_DISABLED" in error_msg:
            # Log audit event for policy violation
            log_audit(
                tenant_id=auth.tenant_id,
                action="share_create_denied",
                actor_id=auth.user_id,
                actor_email=auth.email,
                actor_role=auth.role.value if auth.role else None,
                auth_method=auth.auth_method,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                details={
                    "reason": "public_shares_disabled",
                    "project_id": request.project_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "PUBLIC_SHARES_DISABLED", "message": "Project does not allow public shares"},
            )
        # v3.8.0: Handle password validation errors
        if "SHARE_PASSWORD_REQUIRED" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "SHARE_PASSWORD_REQUIRED", "message": "Password is required when requires_password is True"},
            )
        if "SHARE_PASSWORD_TOO_WEAK" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "SHARE_PASSWORD_TOO_WEAK", "message": "Password must be at least 10 characters"},
            )
        raise

    # Log audit event for share creation
    log_audit(
        tenant_id=auth.tenant_id,
        action="share_created",
        actor_id=auth.user_id,
        actor_email=auth.email,
        actor_role=auth.role.value if auth.role else None,
        auth_method=auth.auth_method,
        resource_type="share",
        resource_id=share["id"],
        details={
            "shared_resource_type": request.resource_type,
            "shared_resource_id": request.resource_id,
            "project_id": request.project_id,
            "expires_at": share["expires_at"],
            "label": request.label,
            # v3.8.0 fields
            "requires_password": request.requires_password,
            "single_use": request.single_use,
            "max_access_count": request.max_access_count,
        },
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
        project_id=share.get("project_id"),
        # v3.8.0 fields
        requires_password=share.get("requires_password", False),
        single_use=share.get("single_use", False),
        max_access_count=share.get("max_access_count"),
        access_count=share.get("access_count", 0),
        token_version=share.get("token_version", 1),
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

    # Get share details before revoking for audit log
    share = auth_store.get_share_by_id(share_id, auth.tenant_id)

    revoked = auth_store.revoke_share(share_id, auth.tenant_id)

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SHARE_NOT_FOUND", "message": "Share not found or already revoked"},
        )

    # Log audit event for share revocation
    log_audit(
        tenant_id=auth.tenant_id,
        action="share_revoked",
        actor_id=auth.user_id,
        actor_email=auth.email,
        actor_role=auth.role.value if auth.role else None,
        auth_method=auth.auth_method,
        resource_type="share",
        resource_id=share_id,
        details={
            "shared_resource_type": share["resource_type"] if share else None,
            "shared_resource_id": share["resource_id"] if share else None,
            "project_id": share.get("project_id") if share else None,
        },
    )

    return None


# -------------------------------------------------------------------------
# Share Token Rotation and Revoke-All (v3.8.0)
# -------------------------------------------------------------------------


class ShareRotateResponse(BaseModel):
    """Response after rotating share token (v3.8.0)."""
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    token_version: int
    token: str  # New plaintext token - shown only once!


class RevokeAllSharesResponse(BaseModel):
    """Response after revoking all shares (v3.8.0)."""
    revoked_count: int


@router.post("/shares/{share_id}/rotate", response_model=ShareRotateResponse)
def rotate_share_token(
    share_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Rotate a share token (v3.8.0).

    Generates a new token for an existing share, incrementing token_version.
    Old tokens become invalid immediately.

    IMPORTANT: The new share token is returned ONLY in this response.
    Store it securely - it cannot be retrieved later.

    Requires admin role.
    """
    auth_store = get_auth_store()

    # Get share details before rotation for audit log
    share_before = auth_store.get_share_by_id(share_id, auth.tenant_id)

    result = auth_store.rotate_share_token(share_id, auth.tenant_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SHARE_NOT_FOUND", "message": "Share not found or already revoked"},
        )

    # Log audit event for token rotation
    log_audit(
        tenant_id=auth.tenant_id,
        action="share_token_rotated",
        actor_id=auth.user_id,
        actor_email=auth.email,
        actor_role=auth.role.value if auth.role else None,
        auth_method=auth.auth_method,
        resource_type="share",
        resource_id=share_id,
        details={
            "shared_resource_type": result["resource_type"],
            "shared_resource_id": result["resource_id"],
            "old_token_version": share_before.get("token_version", 1) if share_before else 1,
            "new_token_version": result["token_version"],
            "project_id": share_before.get("project_id") if share_before else None,
        },
    )

    return ShareRotateResponse(
        id=result["id"],
        tenant_id=result["tenant_id"],
        resource_type=result["resource_type"],
        resource_id=result["resource_id"],
        token_version=result["token_version"],
        token=result["token"],
    )


@router.post("/projects/{project_id}/shares/revoke-all", response_model=RevokeAllSharesResponse)
def revoke_all_project_shares(
    project_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Revoke all active shares for a project (v3.8.0).

    All active (non-revoked) shares associated with the project will be revoked.
    This is useful for security incidents or when decommissioning a project.

    Requires admin role.
    """
    auth_store = get_auth_store()

    # Verify project exists and user has access
    project = auth_store.get_project(project_id, auth.tenant_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "PROJECT_NOT_FOUND", "message": "Project not found"},
        )

    # Count active shares before revocation for audit
    count_before = auth_store.count_active_shares_for_project(project_id, auth.tenant_id)

    # Revoke all shares
    revoked_count = auth_store.revoke_all_shares_for_project(project_id, auth.tenant_id)

    # Log audit event for bulk revocation
    log_audit(
        tenant_id=auth.tenant_id,
        action="shares_revoked_all",
        actor_id=auth.user_id,
        actor_email=auth.email,
        actor_role=auth.role.value if auth.role else None,
        auth_method=auth.auth_method,
        resource_type="project",
        resource_id=project_id,
        details={
            "project_name": project["name"],
            "shares_revoked": revoked_count,
            "active_shares_before": count_before,
        },
    )

    return RevokeAllSharesResponse(revoked_count=revoked_count)


class RevokeSharesForResourceRequest(BaseModel):
    """Request to revoke all shares for a resource (v3.8.0)."""
    resource_type: str  # "run" or "report"
    resource_id: str


@router.post("/shares/revoke-all", response_model=RevokeAllSharesResponse)
def revoke_all_resource_shares(
    request: RevokeSharesForResourceRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Revoke all active shares for a specific resource (v3.8.0).

    All active (non-revoked) shares for the given resource will be revoked.

    Requires admin role.
    """
    # Validate resource_type
    if request.resource_type not in ("run", "report"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_RESOURCE_TYPE", "message": "resource_type must be 'run' or 'report'"},
        )

    auth_store = get_auth_store()

    revoked_count = auth_store.revoke_all_shares_for_resource(
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        tenant_id=auth.tenant_id,
    )

    # Log audit event for bulk revocation
    log_audit(
        tenant_id=auth.tenant_id,
        action="shares_revoked_for_resource",
        actor_id=auth.user_id,
        actor_email=auth.email,
        actor_role=auth.role.value if auth.role else None,
        auth_method=auth.auth_method,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        details={
            "shares_revoked": revoked_count,
        },
    )

    return RevokeAllSharesResponse(revoked_count=revoked_count)


# -------------------------------------------------------------------------
# Share Access Logs and Stats (v3.8.0 PR3)
# -------------------------------------------------------------------------


class ShareAccessLogEntry(BaseModel):
    """Single access log entry for a share."""
    id: str
    share_id: str
    tenant_id: str
    accessed_at: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    access_result: str  # "success", "denied_share_password_invalid", etc.


class ShareAccessLogsResponse(BaseModel):
    """Response for listing share access logs."""
    items: List[ShareAccessLogEntry]
    total: int


class ShareStatsResponse(BaseModel):
    """Statistics for a share (v3.8.0 PR3)."""
    share_id: str
    total_accesses: int
    successful_accesses: int
    denied_accesses: int
    first_access_at: Optional[str] = None
    last_access_at: Optional[str] = None
    unique_ips: int


@router.get("/shares/{share_id}/access-logs", response_model=ShareAccessLogsResponse)
def get_share_access_logs(
    share_id: str,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get access logs for a share (v3.8.0 PR3).

    Returns paginated list of access attempts with IP, user agent, and result.

    Query parameters:
    - limit: Max entries to return (default 100, max 1000)
    - offset: Number of entries to skip (default 0)

    Requires admin role.
    """
    # Validate limit
    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_LIMIT", "message": "limit must be between 1 and 1000"},
        )

    auth_store = get_auth_store()

    # Verify share exists and belongs to tenant
    share = auth_store.get_share_by_id(share_id, auth.tenant_id)
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SHARE_NOT_FOUND", "message": "Share not found"},
        )

    logs = auth_store.list_share_access_logs(share_id, auth.tenant_id, limit=limit, offset=offset)
    total = auth_store.count_share_access_logs(share_id, auth.tenant_id)

    items = [
        ShareAccessLogEntry(
            id=log["id"],
            share_id=log["share_id"],
            tenant_id=log["tenant_id"],
            accessed_at=log["accessed_at"],
            ip_address=log.get("ip_address"),
            user_agent=log.get("user_agent"),
            access_result=log["access_result"],
        )
        for log in logs
    ]

    return ShareAccessLogsResponse(items=items, total=total)


@router.get("/shares/{share_id}/stats", response_model=ShareStatsResponse)
def get_share_stats(
    share_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    """
    Get statistics for a share (v3.8.0 PR3).

    Returns aggregated stats including:
    - Total access attempts
    - Successful accesses
    - Denied accesses
    - First and last access timestamps
    - Count of unique IP addresses

    Requires admin role.
    """
    auth_store = get_auth_store()

    # Verify share exists and belongs to tenant
    share = auth_store.get_share_by_id(share_id, auth.tenant_id)
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "SHARE_NOT_FOUND", "message": "Share not found"},
        )

    stats = auth_store.get_share_stats(share_id, auth.tenant_id)

    return ShareStatsResponse(
        share_id=share_id,
        total_accesses=stats["total_accesses"],
        successful_accesses=stats["successful_accesses"],
        denied_accesses=stats["denied_accesses"],
        first_access_at=stats.get("first_access_at"),
        last_access_at=stats.get("last_access_at"),
        unique_ips=stats["unique_ips"],
    )
