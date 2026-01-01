"""
HTTP Security middleware for FastAPI.
Adds security headers and tightens CORS configuration.

v3.2.0: Hard Security
"""
import os
from typing import List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Environment configuration
ENV = os.getenv("ENV", "dev")
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"


# Paths that should have Cache-Control: no-store (sensitive endpoints)
NO_STORE_PATHS = [
    "/auth/",
    "/shared/",
    "/api/bess-dispatch/auth/",
    "/api/bess-dispatch/shared/",
]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all responses.

    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: no-referrer
    - Permissions-Policy: geolocation=(), microphone=(), camera=()
    - Cache-Control: no-store (for auth/shared endpoints)
    - Strict-Transport-Security (production only)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Always add these security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Add HSTS only in production (not on localhost)
        if ENV == "prod":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Add Cache-Control: no-store for sensitive endpoints
        path = request.url.path
        if any(path.startswith(p) for p in NO_STORE_PATHS):
            response.headers["Cache-Control"] = "no-store"

        return response


def get_cors_config() -> dict:
    """
    Get CORS configuration from environment.

    Returns dict suitable for CORSMiddleware:
    - allow_origins: list from CORS_ALLOWED_ORIGINS env
    - allow_credentials: from CORS_ALLOW_CREDENTIALS env (default false)
    - allow_methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    - allow_headers: ["*"]
    """
    return {
        "allow_origins": [origin.strip() for origin in CORS_ALLOWED_ORIGINS if origin.strip()],
        "allow_credentials": CORS_ALLOW_CREDENTIALS,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["*"],
    }
