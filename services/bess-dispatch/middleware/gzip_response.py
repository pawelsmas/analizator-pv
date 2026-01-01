"""
GZip Response Middleware (v2.5.0 PR4).

Automatically compresses JSON responses that exceed the threshold size
when client accepts gzip encoding.

Features:
- Automatic Content-Encoding: gzip header
- Respects Accept-Encoding request header
- Configurable compression threshold
- Adds Vary: Accept-Encoding for caching
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from compression_helper import (
    should_compress,
    compress_content,
    COMPRESSION_ENABLED,
    COMPRESSION_THRESHOLD_BYTES,
)


class GZipResponseMiddleware(BaseHTTPMiddleware):
    """
    Middleware to compress JSON responses.

    Only compresses responses when:
    - Client accepts gzip (Accept-Encoding header)
    - Response is JSON content type
    - Response exceeds compression threshold
    """

    async def dispatch(self, request: Request, call_next):
        # Get Accept-Encoding header
        accept_encoding = request.headers.get("Accept-Encoding", "")

        # Call next middleware/endpoint
        response = await call_next(request)

        # Skip if compression disabled or client doesn't accept gzip
        if not COMPRESSION_ENABLED:
            return response

        if "gzip" not in accept_encoding.lower():
            return response

        # Skip if response is streaming
        if not hasattr(response, "body"):
            return response

        # Skip non-JSON responses
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return response

        # Get response body
        body = response.body

        # Skip if below threshold
        if len(body) < COMPRESSION_THRESHOLD_BYTES:
            return response

        # Compress
        compressed_body = compress_content(body)

        # Build new response with compression headers
        headers = dict(response.headers)
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(compressed_body))
        headers["Vary"] = "Accept-Encoding"

        return Response(
            content=compressed_body,
            status_code=response.status_code,
            headers=headers,
            media_type=content_type,
        )
