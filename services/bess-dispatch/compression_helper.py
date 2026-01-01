"""
Compression helper for API responses (v2.5.0 PR4).

Provides:
- GZip compression for JSON responses
- Content-Encoding header handling
- Accept-Encoding detection
- Compression threshold configuration

This reduces bandwidth for large JSON responses (sizing results, batch jobs).
"""

import gzip
import os
from typing import Optional, Tuple
from functools import lru_cache


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Minimum response size to compress (bytes, default: 1KB)
COMPRESSION_THRESHOLD_BYTES = int(os.environ.get("COMPRESSION_THRESHOLD_BYTES", "1024"))

# Compression level (1-9, default: 6 for balanced speed/ratio)
COMPRESSION_LEVEL = int(os.environ.get("COMPRESSION_LEVEL", "6"))

# Enable/disable compression (useful for debugging)
COMPRESSION_ENABLED = os.environ.get("COMPRESSION_ENABLED", "true").lower() == "true"

# Content types eligible for compression
COMPRESSIBLE_CONTENT_TYPES = {
    "application/json",
    "text/plain",
    "text/html",
    "text/csv",
    "application/xml",
    "text/xml",
}


# -----------------------------------------------------------------------------
# Accept-Encoding Parsing
# -----------------------------------------------------------------------------

def accepts_gzip(accept_encoding: Optional[str]) -> bool:
    """
    Check if client accepts gzip encoding.

    Args:
        accept_encoding: Value of Accept-Encoding header

    Returns:
        True if client accepts gzip
    """
    if not accept_encoding:
        return False

    # Parse Accept-Encoding header
    # Examples: "gzip, deflate", "gzip;q=1.0, *;q=0.5"
    for part in accept_encoding.split(","):
        encoding = part.strip().split(";")[0].strip().lower()
        if encoding in ("gzip", "*"):
            return True

    return False


# -----------------------------------------------------------------------------
# Compression Functions
# -----------------------------------------------------------------------------

def compress_content(content: bytes, level: int = None) -> bytes:
    """
    Compress content using gzip.

    Args:
        content: Raw bytes to compress
        level: Compression level (1-9), defaults to COMPRESSION_LEVEL

    Returns:
        Compressed bytes
    """
    if level is None:
        level = COMPRESSION_LEVEL

    return gzip.compress(content, compresslevel=level)


def decompress_content(content: bytes) -> bytes:
    """
    Decompress gzip content.

    Args:
        content: Gzip-compressed bytes

    Returns:
        Decompressed bytes
    """
    return gzip.decompress(content)


def should_compress(
    content_type: Optional[str],
    content_length: int,
    accept_encoding: Optional[str],
) -> bool:
    """
    Determine if response should be compressed.

    Args:
        content_type: Response Content-Type header
        content_length: Response body size in bytes
        accept_encoding: Request Accept-Encoding header

    Returns:
        True if response should be compressed
    """
    if not COMPRESSION_ENABLED:
        return False

    if not accepts_gzip(accept_encoding):
        return False

    if content_length < COMPRESSION_THRESHOLD_BYTES:
        return False

    if not content_type:
        return False

    # Check if content type is compressible (ignore charset etc.)
    base_content_type = content_type.split(";")[0].strip().lower()
    return base_content_type in COMPRESSIBLE_CONTENT_TYPES


def compress_response(
    content: bytes,
    content_type: str,
    accept_encoding: Optional[str],
) -> Tuple[bytes, dict]:
    """
    Conditionally compress response content.

    Args:
        content: Response body bytes
        content_type: Response Content-Type
        accept_encoding: Request Accept-Encoding header

    Returns:
        Tuple of (content, extra_headers)
        If compressed, extra_headers includes Content-Encoding
    """
    if should_compress(content_type, len(content), accept_encoding):
        compressed = compress_content(content)
        return compressed, {
            "Content-Encoding": "gzip",
            "Vary": "Accept-Encoding",
        }

    return content, {}


# -----------------------------------------------------------------------------
# Compression Stats
# -----------------------------------------------------------------------------

def get_compression_stats() -> dict:
    """Get compression configuration for diagnostics."""
    return {
        "enabled": COMPRESSION_ENABLED,
        "threshold_bytes": COMPRESSION_THRESHOLD_BYTES,
        "level": COMPRESSION_LEVEL,
        "compressible_types": list(COMPRESSIBLE_CONTENT_TYPES),
    }
