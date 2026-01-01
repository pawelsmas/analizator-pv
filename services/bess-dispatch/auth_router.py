"""
Auth API router for BESS API (v3.0.0, v3.1.0 invites).

Endpoints:
- POST /auth/login - Login with email/password, get JWT
- GET /auth/me - Get current user info
- POST /auth/accept-invite - Accept invite with token, create account, get JWT
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from auth_config import AuthContext, Role, is_auth_enabled
from auth_deps import get_auth_context
from auth_jwt import create_access_token, get_token_expiry_seconds
from auth_store import get_auth_store, hash_password


router = APIRouter(prefix="/auth", tags=["auth"])


# -------------------------------------------------------------------------
# Request/Response models
# -------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Login request body."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Login response with JWT token."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


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

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expiry_seconds(),
    )


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
    """Response after accepting invite (includes JWT for auto-login)."""
    user_id: str
    email: str
    role: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int


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

    return AcceptInviteResponse(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expiry_seconds(),
    )
