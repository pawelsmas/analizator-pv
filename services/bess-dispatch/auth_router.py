"""
Auth API router for BESS API (v3.0.0, v3.1.0 invites, v3.2.0 refresh tokens).

Endpoints:
- POST /auth/login - Login with email/password, get JWT + refresh token
- POST /auth/refresh - Refresh access token using refresh token
- POST /auth/logout - Revoke refresh token
- GET /auth/me - Get current user info
- POST /auth/accept-invite - Accept invite with token, create account, get JWT
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from auth_config import AuthContext, Role, is_auth_enabled
from auth_deps import get_auth_context
from auth_jwt import create_access_token, get_token_expiry_seconds
from auth_store import get_auth_store, hash_password
from refresh_tokens import (
    create_refresh_token,
    use_refresh_token,
    revoke_refresh_token,
    revoke_all_user_refresh_tokens,
    get_refresh_token_expiry_seconds,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Login request body."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Login response with JWT and refresh token (v3.2.0)."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


class MeResponse(BaseModel):
    """Current user info response."""
    user_id: str | None
    tenant_id: str
    email: str | None
    role: str
    auth_method: str


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """
    Login with email and password.

    Returns JWT access token on success.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "AUTH_DISABLED", "message": "Authentication is disabled"},
        )

    auth_store = get_auth_store()
    user = auth_store.authenticate_user(request.email, request.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )

    # Create JWT token
    token_data = {
        "sub": user["id"],
        "tenant_id": user["tenant_id"],
        "email": user["email"],
        "role": user["role"],
    }
    access_token = create_access_token(token_data)

    # Create refresh token (v3.2.0)
    refresh_token, _ = create_refresh_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        role=user["role"],
    )

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expiry_seconds(),
        refresh_token=refresh_token,
        refresh_expires_in=get_refresh_token_expiry_seconds(),
    )


# -------------------------------------------------------------------------
# Refresh Token (v3.2.0)
# -------------------------------------------------------------------------

class RefreshRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class RefreshResponse(BaseModel):
    """Refresh response with new tokens."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None  # New token if rotation enabled
    refresh_expires_in: Optional[int] = None


@router.post("/refresh", response_model=RefreshResponse)
def refresh(request: RefreshRequest):
    """
    Refresh access token using refresh token.

    If token rotation is enabled (default), returns a new refresh token.
    The old refresh token is invalidated.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "AUTH_DISABLED", "message": "Authentication is disabled"},
        )

    result = use_refresh_token(request.refresh_token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_REFRESH_TOKEN", "message": "Invalid or expired refresh token"},
        )

    user_info, new_refresh_token, _ = result

    # Create new access token
    token_data = {
        "sub": user_info["user_id"],
        "tenant_id": user_info["tenant_id"],
        "email": user_info["email"],
        "role": user_info["role"],
    }
    access_token = create_access_token(token_data)

    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expiry_seconds(),
        refresh_token=new_refresh_token,
        refresh_expires_in=get_refresh_token_expiry_seconds() if new_refresh_token else None,
    )


# -------------------------------------------------------------------------
# Logout (v3.2.0)
# -------------------------------------------------------------------------

class LogoutRequest(BaseModel):
    """Logout request."""
    refresh_token: str
    logout_all: bool = False  # If true, revoke all refresh tokens for user


class LogoutResponse(BaseModel):
    """Logout response."""
    success: bool
    tokens_revoked: int = 1


@router.post("/logout", response_model=LogoutResponse)
def logout(request: LogoutRequest, auth: AuthContext = Depends(get_auth_context)):
    """
    Logout by revoking refresh token.

    If logout_all=true, revokes all refresh tokens for the user.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "AUTH_DISABLED", "message": "Authentication is disabled"},
        )

    if request.logout_all and auth.user_id:
        tokens_revoked = revoke_all_user_refresh_tokens(auth.user_id)
        return LogoutResponse(success=True, tokens_revoked=tokens_revoked)

    success = revoke_refresh_token(request.refresh_token)
    return LogoutResponse(success=success, tokens_revoked=1 if success else 0)


@router.get("/me", response_model=MeResponse)
def get_me(auth: AuthContext = Depends(get_auth_context)):
    """
    Get current authenticated user info.

    Works with JWT, API key, or disabled auth mode.
    """
    return MeResponse(
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        email=auth.email,
        role=auth.role.value if hasattr(auth.role, 'value') else auth.role,
        auth_method=auth.auth_method,
    )


# -------------------------------------------------------------------------
# Accept Invite (v3.1.0)
# -------------------------------------------------------------------------

class AcceptInviteRequest(BaseModel):
    """Request to accept an invite and create account."""
    token: str
    password: str


class AcceptInviteResponse(BaseModel):
    """Response after accepting invite (includes JWT + refresh token for auto-login)."""
    user_id: str
    email: str
    role: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


@router.post("/accept-invite", response_model=AcceptInviteResponse)
def accept_invite(request: AcceptInviteRequest):
    """
    Accept an invite and create a user account.

    This is a public endpoint - no authentication required.
    The invite token serves as proof of authorization.

    Returns JWT token for immediate login.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "AUTH_DISABLED", "message": "Authentication is disabled"},
        )

    # Validate password length
    if len(request.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "PASSWORD_TOO_SHORT", "message": "Password must be at least 6 characters"},
        )

    auth_store = get_auth_store()

    # Get invite by token
    invite = auth_store.get_invite_by_token(request.token)
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "INVITE_NOT_FOUND", "message": "Invite not found or already used"},
        )

    # Check if expired
    if auth_store.is_invite_expired(invite):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error_code": "INVITE_EXPIRED", "message": "Invite has expired"},
        )

    # Check if user already exists (race condition protection)
    if auth_store.email_exists_in_tenant(invite["email"], invite["tenant_id"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "USER_ALREADY_EXISTS", "message": "User already exists"},
        )

    # Create the user
    user = auth_store.create_user(
        tenant_id=invite["tenant_id"],
        email=invite["email"],
        password=request.password,
        role=Role(invite["role"]),
    )

    # Mark invite as accepted
    auth_store.accept_invite(invite["id"])

    # Create JWT token for auto-login
    token_data = {
        "sub": user["id"],
        "tenant_id": user["tenant_id"],
        "email": user["email"],
        "role": user["role"],
    }
    access_token = create_access_token(token_data)

    # Create refresh token (v3.2.0)
    refresh_token, _ = create_refresh_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        role=user["role"],
    )

    return AcceptInviteResponse(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expiry_seconds(),
        refresh_token=refresh_token,
        refresh_expires_in=get_refresh_token_expiry_seconds(),
    )
