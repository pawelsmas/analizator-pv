"""
Versioning helpers for API responses.

Provides schema_version and assumptions_version for all API responses
to ensure frontend and backend are in sync.

v1.8.0: Added git_sha and build_time_utc for /version endpoint.
"""

import hashlib
import os
from pathlib import Path
from typing import Optional

# Schema version - bump when response structure changes
SCHEMA_VERSION = "1.0.0"

# Service name
SERVICE_NAME = "bess-dispatch"

# Assumptions file for hashing
ASSUMPTIONS_FILE = Path(__file__).parent.parent.parent.parent / "docs" / "assumptions.yaml"


def get_schema_version() -> str:
    """Get current API schema version."""
    return SCHEMA_VERSION


def compute_assumptions_hash() -> str:
    """
    Compute SHA256 hash of assumptions.yaml file.

    Returns short hash (first 8 chars) or 'unknown' if file not found.
    """
    try:
        if ASSUMPTIONS_FILE.exists():
            content = ASSUMPTIONS_FILE.read_bytes()
            full_hash = hashlib.sha256(content).hexdigest()
            return full_hash[:8]
        else:
            return "no-file"
    except Exception:
        return "error"


def get_assumptions_version() -> str:
    """
    Get assumptions version string.

    Format: "v1.0-{hash}" where hash is first 8 chars of SHA256.
    """
    file_hash = compute_assumptions_hash()
    return f"v1.0-{file_hash}"


# Pre-computed values (cached at import time)
_cached_schema_version: Optional[str] = None
_cached_assumptions_version: Optional[str] = None


def get_version_info() -> dict:
    """
    Get version info dict for API responses.

    Returns:
        {
            "schema_version": "1.0.0",
            "assumptions_version": "v1.0-abc12345"
        }
    """
    global _cached_schema_version, _cached_assumptions_version

    if _cached_schema_version is None:
        _cached_schema_version = get_schema_version()

    if _cached_assumptions_version is None:
        _cached_assumptions_version = get_assumptions_version()

    return {
        "schema_version": _cached_schema_version,
        "assumptions_version": _cached_assumptions_version,
    }


def get_git_sha() -> str:
    """
    Get git commit SHA from environment variable.

    Returns GIT_SHA env var or 'unknown' if not set.
    """
    return os.environ.get("GIT_SHA", "unknown")


def get_build_time_utc() -> str:
    """
    Get build timestamp from environment variable.

    Returns BUILD_TIME_UTC env var or 'unknown' if not set.
    """
    return os.environ.get("BUILD_TIME_UTC", "unknown")


def get_full_version_info() -> dict:
    """
    Get complete version info dict for /version endpoint.

    Returns:
        {
            "service": "bess-dispatch",
            "git_sha": "abc12345",
            "build_time_utc": "2025-01-01T12:00:00Z",
            "schema_version": "1.0.0",
            "assumptions_version": "v1.0-abc12345"
        }
    """
    version_info = get_version_info()
    return {
        "service": SERVICE_NAME,
        "git_sha": get_git_sha(),
        "build_time_utc": get_build_time_utc(),
        "schema_version": version_info["schema_version"],
        "assumptions_version": version_info["assumptions_version"],
    }
