"""
HA (High Availability) configuration for BESS API (v3.9.0).

Provides fail-closed behavior when HA_MODE=strict:
- Redis unavailable: Reject requests (no in-memory fallback)
- S3/storage unavailable: Reject report generation (no local fallback)
- Database unavailable: Reject all state-modifying operations

Environment Variables:
- HA_MODE: 'permissive' or 'strict' (default: 'permissive')
  - permissive: Fall back to local/in-memory storage when external deps fail
  - strict: Reject requests when external dependencies are unavailable

- REDIS_URL: Redis connection URL (optional in permissive, required in strict)
- S3_BUCKET: S3 bucket for reports (optional in permissive, required in strict)
- DATABASE_URL: Database connection URL

Label cardinality (for Prometheus):
- ha_mode: "permissive" or "strict"
- dependency: "redis", "s3", "database"
- result: "success", "unavailable", "fallback"
"""

import os
from enum import Enum
from typing import Optional

from prometheus_client import Counter


class HAMode(str, Enum):
    """HA mode enum."""
    PERMISSIVE = "permissive"
    STRICT = "strict"


# Configuration from environment
HA_MODE = HAMode(os.getenv("HA_MODE", "permissive").lower())

# Dependency URLs (for health checks)
REDIS_URL = os.getenv("REDIS_URL", "")
S3_BUCKET = os.getenv("S3_BUCKET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


# -------------------------------------------------------------------------
# Prometheus Metrics
# -------------------------------------------------------------------------

HA_DEPENDENCY_CHECKS_TOTAL = Counter(
    "bess_ha_dependency_checks_total",
    "Total HA dependency health checks",
    ["dependency", "result"],
)

HA_FALLBACK_USED_TOTAL = Counter(
    "bess_ha_fallback_used_total",
    "Total times fallback was used (only in permissive mode)",
    ["dependency"],
)

HA_REQUEST_REJECTED_TOTAL = Counter(
    "bess_ha_request_rejected_total",
    "Total requests rejected due to dependency unavailability (strict mode)",
    ["dependency"],
)


# -------------------------------------------------------------------------
# Configuration Functions
# -------------------------------------------------------------------------

def is_ha_strict() -> bool:
    """Check if HA mode is strict (fail-closed)."""
    return HA_MODE == HAMode.STRICT


def is_ha_permissive() -> bool:
    """Check if HA mode is permissive (fallback allowed)."""
    return HA_MODE == HAMode.PERMISSIVE


def validate_ha_config() -> None:
    """
    Validate HA configuration on startup.

    In strict mode, external dependencies must be configured.

    Raises:
        ValueError: If strict mode is enabled but dependencies are not configured
    """
    if is_ha_strict():
        missing = []
        if not REDIS_URL:
            missing.append("REDIS_URL")
        if not S3_BUCKET:
            missing.append("S3_BUCKET")

        if missing:
            raise ValueError(
                f"HA_MODE=strict requires external dependencies: {', '.join(missing)}. "
                "Either configure these or set HA_MODE=permissive."
            )


def get_ha_mode_label() -> str:
    """Get HA mode as string label for metrics."""
    return HA_MODE.value


# -------------------------------------------------------------------------
# Dependency State Tracking
# -------------------------------------------------------------------------

class DependencyState:
    """Tracks the current state of external dependencies."""

    def __init__(self):
        self._redis_available: bool = True
        self._s3_available: bool = True
        self._database_available: bool = True

    @property
    def redis_available(self) -> bool:
        return self._redis_available

    @redis_available.setter
    def redis_available(self, value: bool) -> None:
        self._redis_available = value

    @property
    def s3_available(self) -> bool:
        return self._s3_available

    @s3_available.setter
    def s3_available(self, value: bool) -> None:
        self._s3_available = value

    @property
    def database_available(self) -> bool:
        return self._database_available

    @database_available.setter
    def database_available(self, value: bool) -> None:
        self._database_available = value

    def all_available(self) -> bool:
        """Check if all external dependencies are available."""
        return self._redis_available and self._s3_available and self._database_available

    def to_dict(self) -> dict:
        """Return dependency states as dictionary."""
        return {
            "redis": self._redis_available,
            "s3": self._s3_available,
            "database": self._database_available,
            "all_available": self.all_available(),
        }


# Global dependency state
_dependency_state = DependencyState()


def get_dependency_state() -> DependencyState:
    """Get the global dependency state tracker."""
    return _dependency_state


# -------------------------------------------------------------------------
# HA Decision Functions
# -------------------------------------------------------------------------

class HAUnavailableError(Exception):
    """
    Raised when a dependency is unavailable and HA_MODE=strict.

    This exception should be caught by API handlers and converted to
    a 503 Service Unavailable response.
    """

    def __init__(self, dependency: str, message: Optional[str] = None):
        self.dependency = dependency
        self.message = message or f"{dependency} is unavailable and HA_MODE=strict"
        super().__init__(self.message)


def check_redis_available(operation: str = "cache") -> bool:
    """
    Check if Redis is available for the given operation.

    In strict mode, raises HAUnavailableError if Redis is unavailable.
    In permissive mode, returns False and allows fallback.

    Args:
        operation: Description of the operation (for logging/metrics)

    Returns:
        True if Redis is available, False if unavailable (permissive only)

    Raises:
        HAUnavailableError: If Redis unavailable and HA_MODE=strict
    """
    state = get_dependency_state()

    if state.redis_available:
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="redis", result="success").inc()
        return True

    if is_ha_strict():
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="redis", result="unavailable").inc()
        HA_REQUEST_REJECTED_TOTAL.labels(dependency="redis").inc()
        raise HAUnavailableError(
            "redis",
            f"Redis unavailable for {operation}. HA_MODE=strict prevents fallback."
        )

    # Permissive mode - allow fallback
    HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="redis", result="fallback").inc()
    HA_FALLBACK_USED_TOTAL.labels(dependency="redis").inc()
    return False


def check_s3_available(operation: str = "storage") -> bool:
    """
    Check if S3 is available for the given operation.

    In strict mode, raises HAUnavailableError if S3 is unavailable.
    In permissive mode, returns False and allows fallback.

    Args:
        operation: Description of the operation (for logging/metrics)

    Returns:
        True if S3 is available, False if unavailable (permissive only)

    Raises:
        HAUnavailableError: If S3 unavailable and HA_MODE=strict
    """
    state = get_dependency_state()

    if state.s3_available:
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="s3", result="success").inc()
        return True

    if is_ha_strict():
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="s3", result="unavailable").inc()
        HA_REQUEST_REJECTED_TOTAL.labels(dependency="s3").inc()
        raise HAUnavailableError(
            "s3",
            f"S3 unavailable for {operation}. HA_MODE=strict prevents fallback."
        )

    # Permissive mode - allow fallback
    HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="s3", result="fallback").inc()
    HA_FALLBACK_USED_TOTAL.labels(dependency="s3").inc()
    return False


def check_database_available(operation: str = "query") -> bool:
    """
    Check if database is available for the given operation.

    In strict mode, raises HAUnavailableError if database is unavailable.
    In permissive mode, returns False and allows fallback.

    Args:
        operation: Description of the operation (for logging/metrics)

    Returns:
        True if database is available, False if unavailable (permissive only)

    Raises:
        HAUnavailableError: If database unavailable and HA_MODE=strict
    """
    state = get_dependency_state()

    if state.database_available:
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="database", result="success").inc()
        return True

    if is_ha_strict():
        HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="database", result="unavailable").inc()
        HA_REQUEST_REJECTED_TOTAL.labels(dependency="database").inc()
        raise HAUnavailableError(
            "database",
            f"Database unavailable for {operation}. HA_MODE=strict prevents fallback."
        )

    # Permissive mode - allow fallback
    HA_DEPENDENCY_CHECKS_TOTAL.labels(dependency="database", result="fallback").inc()
    HA_FALLBACK_USED_TOTAL.labels(dependency="database").inc()
    return False


# -------------------------------------------------------------------------
# Health Check Helpers
# -------------------------------------------------------------------------

def update_redis_health(available: bool) -> None:
    """Update Redis availability state (called from health checks)."""
    get_dependency_state().redis_available = available


def update_s3_health(available: bool) -> None:
    """Update S3 availability state (called from health checks)."""
    get_dependency_state().s3_available = available


def update_database_health(available: bool) -> None:
    """Update database availability state (called from health checks)."""
    get_dependency_state().database_available = available


def get_ha_status() -> dict:
    """
    Get comprehensive HA status for health endpoint.

    Returns:
        Dict with ha_mode, dependencies, and overall status
    """
    state = get_dependency_state()

    return {
        "ha_mode": HA_MODE.value,
        "dependencies": state.to_dict(),
        "status": "healthy" if state.all_available() else "degraded",
        "fail_closed": is_ha_strict(),
    }
