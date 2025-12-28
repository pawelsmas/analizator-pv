"""
HTTP metrics for Prometheus instrumentation.

Provides:
- http_requests_total: Counter with service, endpoint, method, status labels
- http_request_duration_seconds: Histogram with service, endpoint, method labels

Label cardinality rules:
- endpoint: Use route template path (e.g., /sizing), NOT full URL with query params
- status: HTTP status code as string (200, 404, 500, etc.)
- method: HTTP method (GET, POST, etc.)
- service: Service name (bess-dispatch)
"""

from prometheus_client import Counter, Histogram

SERVICE_NAME = "bess-dispatch"

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "endpoint", "method", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "endpoint", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)
