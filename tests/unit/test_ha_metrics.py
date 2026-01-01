"""
Unit tests for HA observability metrics (v3.6.0 PR5).

Tests verify:
- Pod info metric is initialized
- Database pool metrics are recorded
- Redis connection metrics are recorded
- Job distribution metrics are recorded
- Health check metrics are recorded
- Graceful shutdown metrics are recorded
"""

import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestPodInfoMetric:
    """Tests for pod identification info metric."""

    def test_pod_info_is_initialized(self):
        """Pod info metric should be initialized."""
        from observability.ha_metrics import pod_info

        # Pod info should exist and be an Info metric
        assert pod_info is not None
        assert "bess_pod" in pod_info._name


class TestDatabasePoolMetrics:
    """Tests for database connection pool metrics."""

    def test_record_db_pool_stats(self):
        """Should record database pool statistics."""
        from observability.ha_metrics import (
            record_db_pool_stats,
            db_pool_size,
            db_pool_checked_out,
            db_pool_overflow,
        )

        record_db_pool_stats("default", size=10, checked_out=5, overflow=2)

        assert db_pool_size.labels(pool_name="default")._value.get() == 10
        assert db_pool_checked_out.labels(pool_name="default")._value.get() == 5
        assert db_pool_overflow.labels(pool_name="default")._value.get() == 2

    def test_db_pool_timeout_counter(self):
        """Database pool timeout counter should exist."""
        from observability.ha_metrics import db_pool_timeout_total

        db_pool_timeout_total.labels(pool_name="default").inc()
        assert db_pool_timeout_total.labels(pool_name="default")._value.get() >= 1

    def test_db_query_duration_histogram(self):
        """Database query duration histogram should exist."""
        from observability.ha_metrics import db_query_duration_seconds

        db_query_duration_seconds.labels(query_type="select").observe(0.05)
        # Histogram exists and accepts observations
        assert True


class TestRedisMetrics:
    """Tests for Redis connection metrics."""

    def test_record_redis_pool_stats(self):
        """Should record Redis pool statistics."""
        from observability.ha_metrics import (
            record_redis_pool_stats,
            redis_connections_active,
            redis_connections_available,
        )

        record_redis_pool_stats("default", active=5, available=15)

        assert redis_connections_active.labels(connection_pool="default")._value.get() == 5
        assert redis_connections_available.labels(connection_pool="default")._value.get() == 15

    def test_redis_command_duration_histogram(self):
        """Redis command duration histogram should exist."""
        from observability.ha_metrics import redis_command_duration_seconds

        redis_command_duration_seconds.labels(command="GET").observe(0.001)
        assert True

    def test_redis_connection_errors_counter(self):
        """Redis connection errors counter should exist."""
        from observability.ha_metrics import redis_connection_errors_total

        redis_connection_errors_total.labels(error_type="timeout").inc()
        assert redis_connection_errors_total.labels(error_type="timeout")._value.get() >= 1


class TestJobDistributionMetrics:
    """Tests for job distribution metrics."""

    def test_record_job_assigned(self):
        """Should record job assignment."""
        from observability.ha_metrics import (
            record_job_assigned,
            jobs_assigned_total,
        )

        initial = jobs_assigned_total.labels(job_type="sizing")._value.get()
        record_job_assigned("sizing")
        assert jobs_assigned_total.labels(job_type="sizing")._value.get() == initial + 1

    def test_record_job_processing_start(self):
        """Should increment processing gauge on start."""
        from observability.ha_metrics import (
            record_job_processing_start,
            jobs_processing,
        )

        initial = jobs_processing.labels(job_type="sizing")._value.get()
        record_job_processing_start("sizing")
        assert jobs_processing.labels(job_type="sizing")._value.get() == initial + 1

    def test_record_job_completed(self):
        """Should update metrics on job completion."""
        from observability.ha_metrics import (
            record_job_processing_start,
            record_job_completed,
            jobs_processing,
            jobs_completed_total,
        )

        # Start a job first
        record_job_processing_start("batch")
        initial_processing = jobs_processing.labels(job_type="batch")._value.get()
        initial_completed = jobs_completed_total.labels(job_type="batch", status="success")._value.get()

        # Complete the job
        record_job_completed("batch", "success", 1.5)

        assert jobs_processing.labels(job_type="batch")._value.get() == initial_processing - 1
        assert jobs_completed_total.labels(job_type="batch", status="success")._value.get() == initial_completed + 1


class TestWorkerQueueMetrics:
    """Tests for worker queue metrics."""

    def test_worker_queue_length_gauge(self):
        """Worker queue length gauge should exist."""
        from observability.ha_metrics import worker_queue_length

        worker_queue_length.labels(queue_name="default").set(42)
        assert worker_queue_length.labels(queue_name="default")._value.get() == 42

    def test_worker_queue_oldest_gauge(self):
        """Worker queue oldest job age gauge should exist."""
        from observability.ha_metrics import worker_queue_oldest_seconds

        worker_queue_oldest_seconds.labels(queue_name="default").set(120.5)
        assert worker_queue_oldest_seconds.labels(queue_name="default")._value.get() == 120.5

    def test_worker_prefetch_count_gauge(self):
        """Worker prefetch count gauge should exist."""
        from observability.ha_metrics import worker_prefetch_count

        worker_prefetch_count.labels(queue_name="default").set(4)
        assert worker_prefetch_count.labels(queue_name="default")._value.get() == 4


class TestHealthCheckMetrics:
    """Tests for health check metrics."""

    def test_record_health_check_success(self):
        """Should record successful health check."""
        from observability.ha_metrics import (
            record_health_check,
            health_check_total,
            component_healthy,
        )

        initial = health_check_total.labels(check_type="database", result="success")._value.get()
        record_health_check("database", healthy=True, duration_seconds=0.01)

        assert health_check_total.labels(check_type="database", result="success")._value.get() == initial + 1
        assert component_healthy.labels(component="database")._value.get() == 1

    def test_record_health_check_failure(self):
        """Should record failed health check."""
        from observability.ha_metrics import (
            record_health_check,
            health_check_total,
            component_healthy,
        )

        initial = health_check_total.labels(check_type="redis", result="failure")._value.get()
        record_health_check("redis", healthy=False, duration_seconds=0.5)

        assert health_check_total.labels(check_type="redis", result="failure")._value.get() == initial + 1
        assert component_healthy.labels(component="redis")._value.get() == 0


class TestGracefulShutdownMetrics:
    """Tests for graceful shutdown metrics."""

    def test_record_shutdown_initiated(self):
        """Should record shutdown initiation."""
        from observability.ha_metrics import (
            record_shutdown_initiated,
            shutdown_initiated,
        )

        record_shutdown_initiated()
        assert shutdown_initiated._value.get() == 1

    def test_record_shutdown_complete(self):
        """Should record shutdown completion duration."""
        from observability.ha_metrics import (
            record_shutdown_complete,
            shutdown_duration_seconds,
        )

        # Should not raise
        record_shutdown_complete(45.0)
        assert True

    def test_shutdown_jobs_remaining_gauge(self):
        """Shutdown jobs remaining gauge should exist."""
        from observability.ha_metrics import shutdown_jobs_remaining

        shutdown_jobs_remaining.set(5)
        assert shutdown_jobs_remaining._value.get() == 5


class TestHelmPrometheusRuleTemplate:
    """Tests for Helm PrometheusRule template."""

    def test_prometheusrule_template_exists(self):
        """PrometheusRule template should exist."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "prometheusrule.yaml"
        assert template_path.exists()

    def test_prometheusrule_has_ha_alerts(self):
        """PrometheusRule should contain HA alerts."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "prometheusrule.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "PVPortalAPIPodsBelowMinimum" in content
        assert "PVPortalWorkerPodsBelowMinimum" in content
        assert "PVPortalDBPoolTimeouts" in content
        assert "PVPortalRedisConnectionErrors" in content

    def test_prometheusrule_is_conditional(self):
        """PrometheusRule should be conditional on monitoring.prometheusRule.enabled."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "prometheusrule.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.monitoring.prometheusRule.enabled" in content


class TestHelmServiceMonitorTemplate:
    """Tests for Helm ServiceMonitor template."""

    def test_servicemonitor_template_exists(self):
        """ServiceMonitor template should exist."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "servicemonitor.yaml"
        assert template_path.exists()

    def test_servicemonitor_has_api_and_worker(self):
        """ServiceMonitor should define both API and Worker monitors."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "servicemonitor.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "-api" in content
        assert "-worker" in content
        assert "/metrics" in content

    def test_servicemonitor_is_conditional(self):
        """ServiceMonitor should be conditional on monitoring.serviceMonitor.enabled."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "servicemonitor.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.monitoring.serviceMonitor.enabled" in content


class TestHelmGrafanaDashboard:
    """Tests for Helm Grafana dashboard ConfigMap."""

    def test_grafana_dashboard_template_exists(self):
        """Grafana dashboard template should exist."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "grafana-dashboard.yaml"
        assert template_path.exists()

    def test_grafana_dashboard_is_configmap(self):
        """Grafana dashboard should be a ConfigMap."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "grafana-dashboard.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "kind: ConfigMap" in content
        assert "grafana_dashboard" in content

    def test_grafana_dashboard_has_panels(self):
        """Grafana dashboard should have HA-related panels."""
        from pathlib import Path

        template_path = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal" / "templates" / "grafana-dashboard.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "API Pods Up" in content
        assert "Worker Pods Up" in content
        assert "DB Connection Pool" in content
        assert "Redis Connections" in content
        assert "Queue Length" in content


class TestAlertsDocumentation:
    """Tests for ALERTS.md documentation."""

    def test_alerts_md_has_ha_section(self):
        """ALERTS.md should have HA Infrastructure section."""
        from pathlib import Path

        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        with open(alerts_path, "r") as f:
            content = f.read()

        assert "## HA Infrastructure Alerts (v3.6.0)" in content

    def test_alerts_md_has_runbook_summary(self):
        """ALERTS.md should have HA Runbook Summary."""
        from pathlib import Path

        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        with open(alerts_path, "r") as f:
            content = f.read()

        assert "## HA Runbook Summary" in content
        assert "PodsBelowMinimum" in content
        assert "DBPoolTimeouts" in content
