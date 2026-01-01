"""
Request Size Limit Middleware (v2.5.0).

Enforces maximum request body size to prevent memory exhaustion.
Returns 413 Payload Too Large with structured error response.
"""

import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from limits_config import MAX_REQUEST_BYTES, ErrorCode


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that limits request body size.

    Returns 413 with error_code if Content-Length exceeds limit
    or if body size exceeds limit after reading.
    """

    def __init__(self, app, max_bytes: int = None):
        super().__init__(app)
        self.max_bytes = max_bytes if max_bytes is not None else MAX_REQUEST_BYTES

    async def dispatch(self, request: Request, call_next):
        # Skip size check for GET, HEAD, OPTIONS
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Check Content-Length header if present
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_bytes:
                    return self._too_large_response(length)
            except ValueError:
                pass  # Invalid Content-Length, let it through for body check

        # If no Content-Length or need to verify, check body size
        # This is done by reading the body and checking size
        # Note: We need to cache the body for later use
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self.max_bytes:
                return self._too_large_response(len(body))

            # Cache body for later handlers
            # This is handled by Starlette's request.body() caching

        return await call_next(request)

    def _too_large_response(self, actual_size: int = None) -> JSONResponse:
        """Return 413 response with structured error."""
        # Track limit rejection (v2.5.0 PR6)
        from observability.perf_metrics import track_limit_rejection
        track_limit_rejection("request_size")

        error_body = {
            "error_code": ErrorCode.REQUEST_TOO_LARGE,
            "detail": f"Request body exceeds maximum allowed size of {self.max_bytes} bytes",
            "max_request_bytes": self.max_bytes,
        }
        if actual_size is not None:
            error_body["actual_bytes"] = actual_size

        return JSONResponse(
            status_code=413,
            content=error_body,
        )
