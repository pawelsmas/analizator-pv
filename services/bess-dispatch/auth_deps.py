"""
FastAPI authentication dependencies (v3.0.0).

Provides get_auth_context() dependency for protected endpoints.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_config import (
    AuthContext,
    DEFAULT_TENANT_ID,
    Role,
    is_auth_enabled,
)
from auth_jwt import decode_access_token
from auth_store import get_auth_store, hash_api_key


# Optional bearer token security
http_bearer = HTTPBearer(auto_error=False)


def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> AuthContext:
    """
    Get authentication context from request.

    When AUTH_MODE=disabled:
        Returns default context with admin role.

    When AUTH_MODE=enabled:
        Requires either:
        - Authorization: Bearer <JWT>
        - X-API-Key: <key>

    Raises:
        HTTPException 401 if auth required but not provided/invalid
    """
    # If auth is disabled, return default context
    if not is_auth_enabled():
        return AuthContext(
            tenant_id=DEFAULT_TENANT_ID,
            user_id=None,
            email=None,
            role=Role.ADMIN,
            auth_method="disabled",
        )

    # Check for API key header first
    api_key = request.headers.get("X-API-Key")
    if api_key:
        auth_store = get_auth_store()
        key_info = auth_store.authenticate_api_key(api_key)
        if key_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_API_KEY", "message": "Invalid or revoked API key"},
            )
        return AuthContext(
            tenant_id=key_info["tenant_id"],
            user_id=None,
            email=None,
            role=Role(key_info["role"]),
            auth_method="api_key",
        )

    # Check for Bearer token
    if credentials:
        token = credentials.credentials
        payload = decode_access_token(token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "INVALID_TOKEN", "message": "Invalid or expired token"},
            )
        return AuthContext(
            tenant_id=payload.get("tenant_id", DEFAULT_TENANT_ID),
            user_id=payload.get("sub"),
            email=payload.get("email"),
            role=Role(payload.get("role", "viewer")),
            auth_method="jwt",
        )

    # No auth provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": "AUTH_REQUIRED", "message": "Authentication required"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(min_role: Role):
    """
    Create a dependency that requires a minimum role level.

    Usage:
        @app.get("/admin", dependencies=[Depends(require_role(Role.ADMIN))])

    Args:
        min_role: Minimum required role

    Returns:
        Dependency function
    """
    def role_checker(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.role.has_permission(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "FORBIDDEN",
                    "message": f"Requires at least {min_role.value} role",
                },
            )
        return auth
    return role_checker


def get_optional_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> Optional[AuthContext]:
    """
    Get authentication context, or None if not provided.

    Useful for endpoints that work differently with/without auth.
    """
    try:
        return get_auth_context(request, credentials)
    except HTTPException:
        return None
