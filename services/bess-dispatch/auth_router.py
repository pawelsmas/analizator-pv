"""
Auth API router for BESS API (v3.0.0).

Endpoints:
- POST /auth/login - Login with email/password, get JWT
- GET /auth/me - Get current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from auth_config import AuthContext, is_auth_enabled
from auth_deps import get_auth_context
from auth_jwt import create_access_token, get_token_expiry_seconds
from auth_store import get_auth_store


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
