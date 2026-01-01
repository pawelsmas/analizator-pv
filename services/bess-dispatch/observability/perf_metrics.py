"""
Performance metrics for request/response monitoring (v2.5.0 PR6).

Tracks:
- Request body size distribution
- Response body size distribution
- Slow request counts (> threshold)
- Report cache hit/miss rates
- Compression savings

These metrics enable performance monitoring and alerting.
"""

import os
from prometheus_client import Counter, Histogram, Gauge


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Slow request threshold in seconds (default: 2s)
SLOW_REQUEST_THRESHOLD_SECONDS = float(os.environ.get("SLOW_REQUEST_THRESHOLD_SECONDS", "2.0"))


# -----------------------------------------------------------------------------
# Request/Response Size Metrics
# -----------------------------------------------------------------------------

REQUEST_SIZE_BYTES = Histogram(
    "bess_request_size_bytes",
    "Request body size in bytes",
    ["endpoint"],
    buckets=[100, 1000, 10000, 100000, 500000, 1000000, 2500000],
)

RESPONSE_SIZE_BYTES = Histogram(
    "bess_response_size_bytes",
    "Response body size in bytes",
    ["endpoint"],
    buckets=[1000, 10000, 50000, 100000, 500000, 1000000, 5000000],
)

RESPONSE_SIZE_COMPRESSED_BYTES = Histogram(
    "bess_response_size_compressed_bytes",
    "Compressed response body size in bytes",
    ["endpoint"],
    buckets=[100, 1000, 5000, 10000, 50000, 100000, 500000],
)


# -----------------------------------------------------------------------------
# Slow Request Metrics
# -----------------------------------------------------------------------------

SLOW_REQUESTS_TOTAL = Counter(
    "bess_slow_requests_total",
    "Total requests exceeding slow threshold",
    ["endpoint", "method"],
)

REQUEST_DURATION_SECONDS = Histogram(
    "bess_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint", "method"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)


# -----------------------------------------------------------------------------
# Cache Metrics
# -----------------------------------------------------------------------------

REPORT_CACHE_HITS_TOTAL = Counter(
    "bess_report_cache_hits_total",
    "Total report cache hits",
    ["format"],  # pdf, xlsx, zip
)

REPORT_CACHE_MISSES_TOTAL = Counter(
    "bess_report_cache_misses_total",
    "Total report cache misses",
    ["format"],
)

REPORT_CACHE_SIZE_ENTRIES = Gauge(
    "bess_report_cache_size_entries",
    "Current number of entries in report cache",
    ["format"],
)


# -----------------------------------------------------------------------------
# Compression Metrics
# -----------------------------------------------------------------------------

COMPRESSION_RATIO = Histogram(
    "bess_compression_ratio",
    "Compression ratio (compressed/original)",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

COMPRESSION_SAVINGS_BYTES = Counter(
    "bess_compression_savings_bytes_total",
    "Total bytes saved by compression",
)


# -----------------------------------------------------------------------------
# Limit Enforcement Metrics
# -----------------------------------------------------------------------------

LIMIT_REJECTIONS_TOTAL = Counter(
    "bess_limit_rejections_total",
    "Total requests rejected due to limits",
    ["limit_type"],  # request_size, steps, timeseries
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def track_request_size(endpoint: str, size_bytes: int):
    """Track request body size."""
    REQUEST_SIZE_BYTES.labels(endpoint=endpoint).observe(size_bytes)


def track_response_size(endpoint: str, size_bytes: int, compressed_bytes: int = None):
    """Track response body size (with optional compressed size)."""
    RESPONSE_SIZE_BYTES.labels(endpoint=endpoint).observe(size_bytes)
    if compressed_bytes is not None:
        RESPONSE_SIZE_COMPRESSED_BYTES.labels(endpoint=endpoint).observe(compressed_bytes)
        if size_bytes > 0:
            ratio = compressed_bytes / size_bytes
            COMPRESSION_RATIO.observe(ratio)
            savings = size_bytes - compressed_bytes
            if savings > 0:
                COMPRESSION_SAVINGS_BYTES.inc(savings)


def track_request_duration(endpoint: str, method: str, duration_seconds: float):
    """Track request duration and count slow requests."""
    REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, method=method).observe(duration_seconds)
    if duration_seconds > SLOW_REQUEST_THRESHOLD_SECONDS:
        SLOW_REQUESTS_TOTAL.labels(endpoint=endpoint, method=method).inc()


def track_report_cache_hit(format: str):
    """Track report cache hit."""
    REPORT_CACHE_HITS_TOTAL.labels(format=format).inc()


def track_report_cache_miss(format: str):
    """Track report cache miss."""
    REPORT_CACHE_MISSES_TOTAL.labels(format=format).inc()


def update_report_cache_size(format: str, count: int):
    """Update report cache size gauge."""
    REPORT_CACHE_SIZE_ENTRIES.labels(format=format).set(count)


def track_limit_rejection(limit_type: str):
    """Track request rejected due to limit."""
    LIMIT_REJECTIONS_TOTAL.labels(limit_type=limit_type).inc()


def get_perf_config() -> dict:
    """Return performance configuration for diagnostics."""
    return {
        "slow_request_threshold_seconds": SLOW_REQUEST_THRESHOLD_SECONDS,
    }
