"""
Async jobs metrics for Prometheus instrumentation (v1.2.0).

Provides:
- Counters for job creation, completion, cancellation
- Histograms for job duration and items count
- Status-labeled counters for job transitions
- Retention, pruning, and vacuum metrics (v1.2.0)
- SSE progress streaming metrics (v1.2.0)

Label cardinality rules:
- status: pending, running, done, failed, cancelled (5 values)
- wait_mode: sync, async (2 values)
- No high-cardinality labels (job_id, batch_id excluded)
"""

from prometheus_client import Counter, Histogram


# ============================================
# JOB CREATION METRICS
# ============================================

JOBS_CREATED_TOTAL = Counter(
    "bess_jobs_created_total",
    "Total jobs created",
    ["wait_mode"],  # sync or async
)

JOBS_IDEMPOTENCY_HIT_TOTAL = Counter(
    "bess_jobs_idempotency_hit_total",
    "Jobs returned from idempotency cache",
)

JOBS_ITEMS_COUNT = Histogram(
    "bess_jobs_items_count",
    "Number of items per job",
    buckets=(1, 2, 3, 5, 10, 20, 50, 100),
)


# ============================================
# JOB STATUS METRICS
# ============================================

JOBS_STATUS_TRANSITIONS = Counter(
    "bess_jobs_status_transitions_total",
    "Job status transitions",
    ["from_status", "to_status"],
)

JOBS_COMPLETED_TOTAL = Counter(
    "bess_jobs_completed_total",
    "Jobs that completed (done or failed)",
    ["final_status"],  # done or failed
)

JOBS_CANCELLED_TOTAL = Counter(
    "bess_jobs_cancelled_total",
    "Jobs that were cancelled",
)


# ============================================
# JOB TIMING METRICS
# ============================================

JOBS_DURATION_SECONDS = Histogram(
    "bess_jobs_duration_seconds",
    "Job total duration from created to completed",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

JOBS_WAIT_TIME_SECONDS = Histogram(
    "bess_jobs_wait_time_seconds",
    "Time job spent in pending state",
    buckets=(0, 0.1, 0.5, 1, 5, 10, 30, 60, 300),
)

JOBS_PROCESSING_TIME_SECONDS = Histogram(
    "bess_jobs_processing_time_seconds",
    "Time job spent in running state",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)


# ============================================
# JOB RESULT METRICS
# ============================================

JOBS_OK_ITEMS_COUNT = Histogram(
    "bess_jobs_ok_items_count",
    "Number of successful items per completed job",
    buckets=(0, 1, 2, 3, 5, 10, 20, 50, 100),
)

JOBS_ERROR_ITEMS_COUNT = Histogram(
    "bess_jobs_error_items_count",
    "Number of failed items per completed job",
    buckets=(0, 1, 2, 3, 5, 10, 20),
)


# ============================================
# JOB API METRICS
# ============================================

JOBS_GET_TOTAL = Counter(
    "bess_jobs_get_total",
    "Total GET /jobs/{job_id} requests",
    ["found"],  # true or false
)

JOBS_LIST_TOTAL = Counter(
    "bess_jobs_list_total",
    "Total GET /jobs list requests",
    ["has_filters"],  # true or false
)

JOBS_LIST_RESULTS_COUNT = Histogram(
    "bess_jobs_list_results_count",
    "Number of jobs returned per list request",
    buckets=(0, 1, 5, 10, 20, 50, 100),
)

JOBS_CANCEL_TOTAL = Counter(
    "bess_jobs_cancel_total",
    "Total DELETE /jobs/{job_id} cancel requests",
    ["result"],  # cancelled, not_found, already_done
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def record_job_created(wait_mode: str, items_count: int):
    """Record job creation metrics.

    Args:
        wait_mode: 'sync' or 'async'
        items_count: Number of items in the job
    """
    JOBS_CREATED_TOTAL.labels(wait_mode=wait_mode).inc()
    JOBS_ITEMS_COUNT.observe(items_count)


def record_job_idempotency_hit():
    """Record when job is returned from idempotency cache."""
    JOBS_IDEMPOTENCY_HIT_TOTAL.inc()


def record_job_status_transition(from_status: str, to_status: str):
    """Record job status transition.

    Args:
        from_status: Previous status (pending, running, etc.)
        to_status: New status
    """
    JOBS_STATUS_TRANSITIONS.labels(from_status=from_status, to_status=to_status).inc()


def record_job_completed(
    final_status: str,
    duration_seconds: float,
    ok_count: int,
    error_count: int,
):
    """Record job completion metrics.

    Args:
        final_status: 'done' or 'failed'
        duration_seconds: Total job duration
        ok_count: Number of successful items
        error_count: Number of failed items
    """
    JOBS_COMPLETED_TOTAL.labels(final_status=final_status).inc()
    JOBS_DURATION_SECONDS.observe(duration_seconds)
    JOBS_OK_ITEMS_COUNT.observe(ok_count)
    JOBS_ERROR_ITEMS_COUNT.observe(error_count)


def record_job_cancelled():
    """Record job cancellation."""
    JOBS_CANCELLED_TOTAL.inc()


def record_job_wait_time(wait_seconds: float):
    """Record time job spent in pending state."""
    JOBS_WAIT_TIME_SECONDS.observe(wait_seconds)


def record_job_processing_time(processing_seconds: float):
    """Record time job spent in running state."""
    JOBS_PROCESSING_TIME_SECONDS.observe(processing_seconds)


def record_job_get(found: bool):
    """Record GET job detail request.

    Args:
        found: Whether the job was found
    """
    JOBS_GET_TOTAL.labels(found=str(found).lower()).inc()


def record_job_list(has_filters: bool, results_count: int):
    """Record job list request.

    Args:
        has_filters: Whether status/type filters were applied
        results_count: Number of jobs returned
    """
    JOBS_LIST_TOTAL.labels(has_filters=str(has_filters).lower()).inc()
    JOBS_LIST_RESULTS_COUNT.observe(results_count)


def record_job_cancel(result: str):
    """Record job cancel request result.

    Args:
        result: 'cancelled', 'not_found', or 'already_done'
    """
    JOBS_CANCEL_TOTAL.labels(result=result).inc()


# ============================================
# JOB RETENTION/PRUNING/VACUUM METRICS (v1.2.0)
# ============================================

JOBS_PRUNE_TOTAL = Counter(
    "bess_jobs_prune_total",
    "Total POST /jobs:prune requests",
)

JOBS_PRUNED_COUNT = Histogram(
    "bess_jobs_pruned_count",
    "Number of jobs deleted per prune operation",
    buckets=(0, 1, 5, 10, 25, 50, 100, 500, 1000),
)

JOBS_PRUNE_RETENTION_DAYS = Histogram(
    "bess_jobs_prune_retention_days",
    "Retention days used in prune operations",
    buckets=(1, 3, 7, 14, 30, 60, 90, 180, 365),
)

JOBS_VACUUM_TOTAL = Counter(
    "bess_jobs_vacuum_total",
    "Total POST /jobs:vacuum requests",
)

JOBS_VACUUM_FREED_BYTES = Histogram(
    "bess_jobs_vacuum_freed_bytes",
    "Bytes freed by vacuum operations",
    buckets=(0, 1024, 10240, 102400, 1048576, 10485760, 104857600),  # 0, 1KB, 10KB, 100KB, 1MB, 10MB, 100MB
)

JOBS_STATS_TOTAL = Counter(
    "bess_jobs_stats_total",
    "Total GET /jobs/stats requests",
)

JOBS_RETENTION_CONFIG_TOTAL = Counter(
    "bess_jobs_retention_config_total",
    "Total GET /jobs/retention requests",
)


# ============================================
# SSE STREAMING METRICS (v1.2.0)
# ============================================

JOBS_SSE_CONNECTIONS_TOTAL = Counter(
    "bess_jobs_sse_connections_total",
    "Total SSE event stream connections",
    ["job_status"],  # pending, running, done, failed, cancelled
)

JOBS_SSE_EVENTS_SENT_TOTAL = Counter(
    "bess_jobs_sse_events_sent_total",
    "Total SSE events sent",
    ["event_type"],  # status, done, error, cancelled
)

JOBS_SSE_CONNECTION_DURATION_SECONDS = Histogram(
    "bess_jobs_sse_connection_duration_seconds",
    "Duration of SSE connections in seconds",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)


# ============================================
# JOB EXPORT METRICS (v1.2.0)
# ============================================

JOBS_EXPORT_TOTAL = Counter(
    "bess_jobs_export_total",
    "Total job export requests",
    ["format"],  # json, csv, zip
)


# ============================================
# v1.2.0 HELPER FUNCTIONS
# ============================================

def record_jobs_prune(deleted_count: int, retention_days: int):
    """Record job prune operation.

    Args:
        deleted_count: Number of jobs deleted
        retention_days: Retention days used
    """
    JOBS_PRUNE_TOTAL.inc()
    JOBS_PRUNED_COUNT.observe(deleted_count)
    JOBS_PRUNE_RETENTION_DAYS.observe(retention_days)


def record_jobs_vacuum(freed_bytes: int):
    """Record job vacuum operation.

    Args:
        freed_bytes: Bytes freed by vacuum
    """
    JOBS_VACUUM_TOTAL.inc()
    JOBS_VACUUM_FREED_BYTES.observe(freed_bytes)


def record_jobs_stats():
    """Record job stats request."""
    JOBS_STATS_TOTAL.inc()


def record_jobs_retention_config():
    """Record job retention config request."""
    JOBS_RETENTION_CONFIG_TOTAL.inc()


def record_sse_connection(job_status: str):
    """Record SSE connection.

    Args:
        job_status: Status of job when connection established
    """
    JOBS_SSE_CONNECTIONS_TOTAL.labels(job_status=job_status).inc()


def record_sse_event(event_type: str):
    """Record SSE event sent.

    Args:
        event_type: Type of event (status, done, error, cancelled)
    """
    JOBS_SSE_EVENTS_SENT_TOTAL.labels(event_type=event_type).inc()


def record_sse_connection_duration(duration_seconds: float):
    """Record SSE connection duration.

    Args:
        duration_seconds: Duration of SSE connection
    """
    JOBS_SSE_CONNECTION_DURATION_SECONDS.observe(duration_seconds)


def record_job_export(format: str):
    """Record job export request.

    Args:
        format: Export format (json, csv, zip)
    """
    JOBS_EXPORT_TOTAL.labels(format=format).inc()
