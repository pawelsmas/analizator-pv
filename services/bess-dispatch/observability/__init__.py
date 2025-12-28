"""
Observability module for bess-dispatch service.

Contains HTTP metrics instrumentation for Prometheus.
"""

from .http_metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    SERVICE_NAME,
)

__all__ = [
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "SERVICE_NAME",
]
