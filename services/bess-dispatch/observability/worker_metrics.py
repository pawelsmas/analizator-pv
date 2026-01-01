"""
Worker metrics for Prometheus instrumentation (v3.4.0 PR6).

Provides:
- Counters for job claims, executions, completions
- Histograms for job processing times
- Gauges for worker state
- Retry and error tracking metrics

Label cardinality rules:
- job_kind: sizing_batch, report_run, report_portfolio, validate_pack (4 values)
- result: success, failure, retry (3 values)
- worker_id: Not included as high-cardinality label
"""

from prometheus_client import Counter, Histogram, Gauge


# ============================================
# WORKER LIFECYCLE METRICS
# ============================================

WORKER_STARTED_TOTAL = Counter(
    "bess_worker_started_total",
    "Total times worker process has started",
)

WORKER_SHUTDOWN_TOTAL = Counter(
    "bess_worker_shutdown_total",
    "Total times worker process has shutdown gracefully",
)

WORKER_HEARTBEAT_TIMESTAMP = Gauge(
    "bess_worker_heartbeat_timestamp_seconds",
    "Unix timestamp of last worker heartbeat",
)


# ============================================
# JOB CLAIM METRICS
# ============================================

WORKER_JOB_CLAIMS_TOTAL = Counter(
    "bess_worker_job_claims_total",
    "Total jobs claimed by workers",
    ["job_kind"],
)

WORKER_JOB_CLAIM_EMPTY_TOTAL = Counter(
    "bess_worker_job_claim_empty_total",
    "Times worker polled but no jobs available",
)

WORKER_JOB_CLAIM_DURATION_SECONDS = Histogram(
    "bess_worker_job_claim_duration_seconds",
    "Time to claim a job from queue",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1),
)


# ============================================
# JOB EXECUTION METRICS
# ============================================

WORKER_JOB_EXECUTIONS_TOTAL = Counter(
    "bess_worker_job_executions_total",
    "Total job execution attempts",
    ["job_kind", "result"],  # result: success, failure, retry
)

WORKER_JOB_EXECUTION_DURATION_SECONDS = Histogram(
    "bess_worker_job_execution_duration_seconds",
    "Time to execute a job (excluding claim time)",
    ["job_kind"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)

WORKER_JOB_RETRIES_TOTAL = Counter(
    "bess_worker_job_retries_total",
    "Jobs returned to queue for retry",
    ["job_kind"],
)

WORKER_JOB_FAILURES_TOTAL = Counter(
    "bess_worker_job_failures_total",
    "Jobs that permanently failed (max attempts reached)",
    ["job_kind", "error_code"],
)


# ============================================
# JOB ARTIFACT METRICS
# ============================================

WORKER_ARTIFACTS_CREATED_TOTAL = Counter(
    "bess_worker_artifacts_created_total",
    "Total artifacts created by worker",
    ["artifact_type"],  # pdf, xlsx, json, zip
)

WORKER_ARTIFACT_SIZE_BYTES = Histogram(
    "bess_worker_artifact_size_bytes",
    "Size of created artifacts in bytes",
    ["artifact_type"],
    buckets=(1024, 10240, 102400, 1048576, 10485760, 104857600),  # 1KB to 100MB
)


# ============================================
# QUEUE DEPTH METRICS
# ============================================

QUEUE_DEPTH = Gauge(
    "bess_queue_depth",
    "Current number of jobs in queue by status",
    ["status"],  # queued, running
)

QUEUE_OLDEST_JOB_AGE_SECONDS = Gauge(
    "bess_queue_oldest_job_age_seconds",
    "Age of oldest queued job in seconds",
)


# ============================================
# LOCK METRICS
# ============================================

WORKER_LOCK_ACQUIRED_TOTAL = Counter(
    "bess_worker_lock_acquired_total",
    "Times worker acquired a job lock",
)

WORKER_LOCK_RELEASED_TOTAL = Counter(
    "bess_worker_lock_released_total",
    "Times worker released a job lock",
    ["reason"],  # completed, failed, timeout
)

WORKER_LOCK_TIMEOUT_TOTAL = Counter(
    "bess_worker_lock_timeout_total",
    "Times a job lock was reclaimed due to timeout",
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def record_worker_started():
    """Record worker process start."""
    WORKER_STARTED_TOTAL.inc()


def record_worker_shutdown():
    """Record graceful worker shutdown."""
    WORKER_SHUTDOWN_TOTAL.inc()


def record_worker_heartbeat(timestamp: float):
    """Record worker heartbeat.

    Args:
        timestamp: Unix timestamp
    """
    WORKER_HEARTBEAT_TIMESTAMP.set(timestamp)


def record_job_claim(job_kind: str, claim_duration: float):
    """Record successful job claim.

    Args:
        job_kind: Type of job claimed
        claim_duration: Time to claim in seconds
    """
    WORKER_JOB_CLAIMS_TOTAL.labels(job_kind=job_kind).inc()
    WORKER_JOB_CLAIM_DURATION_SECONDS.observe(claim_duration)
    WORKER_LOCK_ACQUIRED_TOTAL.inc()


def record_claim_empty():
    """Record empty poll (no jobs available)."""
    WORKER_JOB_CLAIM_EMPTY_TOTAL.inc()


def record_job_execution(job_kind: str, result: str, duration: float):
    """Record job execution result.

    Args:
        job_kind: Type of job
        result: 'success', 'failure', or 'retry'
        duration: Execution time in seconds
    """
    WORKER_JOB_EXECUTIONS_TOTAL.labels(job_kind=job_kind, result=result).inc()
    WORKER_JOB_EXECUTION_DURATION_SECONDS.labels(job_kind=job_kind).observe(duration)

    if result == "retry":
        WORKER_JOB_RETRIES_TOTAL.labels(job_kind=job_kind).inc()


def record_job_failure(job_kind: str, error_code: str):
    """Record permanent job failure.

    Args:
        job_kind: Type of job
        error_code: Error code from handler
    """
    WORKER_JOB_FAILURES_TOTAL.labels(job_kind=job_kind, error_code=error_code).inc()


def record_artifact_created(artifact_type: str, size_bytes: int):
    """Record artifact creation.

    Args:
        artifact_type: Type of artifact (pdf, xlsx, json, zip)
        size_bytes: Size of artifact in bytes
    """
    WORKER_ARTIFACTS_CREATED_TOTAL.labels(artifact_type=artifact_type).inc()
    WORKER_ARTIFACT_SIZE_BYTES.labels(artifact_type=artifact_type).observe(size_bytes)


def record_lock_released(reason: str):
    """Record job lock release.

    Args:
        reason: 'completed', 'failed', or 'timeout'
    """
    WORKER_LOCK_RELEASED_TOTAL.labels(reason=reason).inc()


def record_lock_timeout():
    """Record job lock timeout (reclaimed by another worker)."""
    WORKER_LOCK_TIMEOUT_TOTAL.inc()


def set_queue_depth(status: str, count: int):
    """Set current queue depth.

    Args:
        status: 'queued' or 'running'
        count: Number of jobs
    """
    QUEUE_DEPTH.labels(status=status).set(count)


def set_oldest_job_age(age_seconds: float):
    """Set age of oldest queued job.

    Args:
        age_seconds: Age in seconds
    """
    QUEUE_OLDEST_JOB_AGE_SECONDS.set(age_seconds)
