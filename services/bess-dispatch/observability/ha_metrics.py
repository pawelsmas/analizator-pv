"""
HA observability metrics for multi-replica deployments (v3.6.0 PR5).

Provides metrics for monitoring:
- Pod distribution across replicas
- Database connection pool health
- Redis connection status
- Job distribution across workers
- Leader election status (if applicable)
"""

from prometheus_client import Counter, Gauge, Histogram, Info
import os


# Pod identification info
pod_info = Info(
    "bess_pod",
    "Pod identification information",
)

# Initialize pod info from environment
pod_info.info({
    "pod_name": os.getenv("POD_NAME", "unknown"),
    "pod_namespace": os.getenv("POD_NAMESPACE", "default"),
    "node_name": os.getenv("NODE_NAME", "unknown"),
})


# Database connection pool metrics
db_pool_size = Gauge(
    "bess_db_pool_size",
    "Current database connection pool size",
    ["pool_name"],
)

db_pool_checked_out = Gauge(
    "bess_db_pool_checked_out",
    "Number of connections currently checked out from pool",
    ["pool_name"],
)

db_pool_overflow = Gauge(
    "bess_db_pool_overflow",
    "Number of connections in overflow",
    ["pool_name"],
)

db_pool_timeout_total = Counter(
    "bess_db_pool_timeout_total",
    "Total number of pool checkout timeouts",
    ["pool_name"],
)

db_query_duration_seconds = Histogram(
    "bess_db_query_duration_seconds",
    "Database query duration in seconds",
    ["query_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


# Redis connection metrics
redis_connections_active = Gauge(
    "bess_redis_connections_active",
    "Number of active Redis connections",
    ["connection_pool"],
)

redis_connections_available = Gauge(
    "bess_redis_connections_available",
    "Number of available Redis connections in pool",
    ["connection_pool"],
)

redis_command_duration_seconds = Histogram(
    "bess_redis_command_duration_seconds",
    "Redis command duration in seconds",
    ["command"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

redis_connection_errors_total = Counter(
    "bess_redis_connection_errors_total",
    "Total number of Redis connection errors",
    ["error_type"],
)


# Job distribution metrics
jobs_assigned_total = Counter(
    "bess_ha_jobs_assigned_total",
    "Total jobs assigned to this pod",
    ["job_type"],
)

jobs_processing = Gauge(
    "bess_ha_jobs_processing",
    "Number of jobs currently processing on this pod",
    ["job_type"],
)

jobs_completed_total = Counter(
    "bess_ha_jobs_completed_total",
    "Total jobs completed by this pod",
    ["job_type", "status"],
)

job_processing_duration_seconds = Histogram(
    "bess_ha_job_processing_duration_seconds",
    "Job processing duration in seconds",
    ["job_type"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)


# Worker queue metrics
worker_queue_length = Gauge(
    "bess_worker_queue_length",
    "Number of jobs waiting in worker queue",
    ["queue_name"],
)

worker_queue_oldest_seconds = Gauge(
    "bess_worker_queue_oldest_seconds",
    "Age of oldest job in queue in seconds",
    ["queue_name"],
)

worker_prefetch_count = Gauge(
    "bess_worker_prefetch_count",
    "Number of prefetched jobs on this worker",
    ["queue_name"],
)


# Health check metrics
health_check_total = Counter(
    "bess_health_check_total",
    "Total health checks performed",
    ["check_type", "result"],
)

health_check_duration_seconds = Histogram(
    "bess_health_check_duration_seconds",
    "Health check duration in seconds",
    ["check_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

component_healthy = Gauge(
    "bess_component_healthy",
    "Component health status (1=healthy, 0=unhealthy)",
    ["component"],
)


# Graceful shutdown metrics
shutdown_initiated = Gauge(
    "bess_shutdown_initiated",
    "Whether graceful shutdown has been initiated (1=yes, 0=no)",
)

shutdown_jobs_remaining = Gauge(
    "bess_shutdown_jobs_remaining",
    "Number of jobs remaining during shutdown",
)

shutdown_duration_seconds = Histogram(
    "bess_shutdown_duration_seconds",
    "Graceful shutdown duration in seconds",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)


def record_db_pool_stats(pool_name: str, size: int, checked_out: int, overflow: int) -> None:
    """Record database connection pool statistics."""
    db_pool_size.labels(pool_name=pool_name).set(size)
    db_pool_checked_out.labels(pool_name=pool_name).set(checked_out)
    db_pool_overflow.labels(pool_name=pool_name).set(overflow)


def record_redis_pool_stats(pool_name: str, active: int, available: int) -> None:
    """Record Redis connection pool statistics."""
    redis_connections_active.labels(connection_pool=pool_name).set(active)
    redis_connections_available.labels(connection_pool=pool_name).set(available)


def record_job_assigned(job_type: str) -> None:
    """Record that a job was assigned to this pod."""
    jobs_assigned_total.labels(job_type=job_type).inc()


def record_job_processing_start(job_type: str) -> None:
    """Record that job processing has started."""
    jobs_processing.labels(job_type=job_type).inc()


def record_job_completed(job_type: str, status: str, duration_seconds: float) -> None:
    """Record that a job has completed."""
    jobs_processing.labels(job_type=job_type).dec()
    jobs_completed_total.labels(job_type=job_type, status=status).inc()
    job_processing_duration_seconds.labels(job_type=job_type).observe(duration_seconds)


def record_health_check(check_type: str, healthy: bool, duration_seconds: float) -> None:
    """Record health check result."""
    result = "success" if healthy else "failure"
    health_check_total.labels(check_type=check_type, result=result).inc()
    health_check_duration_seconds.labels(check_type=check_type).observe(duration_seconds)
    component_healthy.labels(component=check_type).set(1 if healthy else 0)


def record_shutdown_initiated() -> None:
    """Record that graceful shutdown has been initiated."""
    shutdown_initiated.set(1)


def record_shutdown_complete(duration_seconds: float) -> None:
    """Record that graceful shutdown has completed."""
    shutdown_duration_seconds.observe(duration_seconds)
