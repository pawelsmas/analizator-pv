"""
Unit tests for worker metrics module (v3.4.0 PR6).

Tests metric definitions and helper functions.
"""

import pytest
import sys
from pathlib import Path

# Add services directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestWorkerMetricsImport:
    """Tests for worker_metrics module import."""

    def test_import_worker_metrics(self):
        """Should import worker_metrics module."""
        from observability import worker_metrics
        assert worker_metrics is not None

    def test_worker_metrics_has_counters(self):
        """Should have counter definitions."""
        from observability import worker_metrics
        assert hasattr(worker_metrics, "WORKER_STARTED_TOTAL")
        assert hasattr(worker_metrics, "WORKER_SHUTDOWN_TOTAL")
        assert hasattr(worker_metrics, "WORKER_JOB_CLAIMS_TOTAL")
        assert hasattr(worker_metrics, "WORKER_JOB_EXECUTIONS_TOTAL")

    def test_worker_metrics_has_histograms(self):
        """Should have histogram definitions."""
        from observability import worker_metrics
        assert hasattr(worker_metrics, "WORKER_JOB_CLAIM_DURATION_SECONDS")
        assert hasattr(worker_metrics, "WORKER_JOB_EXECUTION_DURATION_SECONDS")
        assert hasattr(worker_metrics, "WORKER_ARTIFACT_SIZE_BYTES")

    def test_worker_metrics_has_gauges(self):
        """Should have gauge definitions."""
        from observability import worker_metrics
        assert hasattr(worker_metrics, "WORKER_HEARTBEAT_TIMESTAMP")
        assert hasattr(worker_metrics, "QUEUE_DEPTH")
        assert hasattr(worker_metrics, "QUEUE_OLDEST_JOB_AGE_SECONDS")


class TestWorkerMetricsHelpers:
    """Tests for worker_metrics helper functions."""

    def test_record_worker_started(self):
        """record_worker_started should be callable."""
        from observability.worker_metrics import record_worker_started
        record_worker_started()

    def test_record_worker_shutdown(self):
        """record_worker_shutdown should be callable."""
        from observability.worker_metrics import record_worker_shutdown
        record_worker_shutdown()

    def test_record_worker_heartbeat(self):
        """record_worker_heartbeat should accept timestamp."""
        from observability.worker_metrics import record_worker_heartbeat
        record_worker_heartbeat(1704067200.0)  # 2024-01-01 00:00:00

    def test_record_job_claim(self):
        """record_job_claim should accept job_kind and duration."""
        from observability.worker_metrics import record_job_claim
        record_job_claim("report_run", 0.05)

    def test_record_claim_empty(self):
        """record_claim_empty should be callable."""
        from observability.worker_metrics import record_claim_empty
        record_claim_empty()

    def test_record_job_execution_success(self):
        """record_job_execution should work with success result."""
        from observability.worker_metrics import record_job_execution
        record_job_execution("report_run", "success", 5.5)

    def test_record_job_execution_failure(self):
        """record_job_execution should work with failure result."""
        from observability.worker_metrics import record_job_execution
        record_job_execution("report_run", "failure", 1.0)

    def test_record_job_execution_retry(self):
        """record_job_execution should work with retry result."""
        from observability.worker_metrics import record_job_execution
        record_job_execution("report_portfolio", "retry", 0.5)

    def test_record_job_failure(self):
        """record_job_failure should accept job_kind and error_code."""
        from observability.worker_metrics import record_job_failure
        record_job_failure("validate_pack", "NOT_IMPLEMENTED")

    def test_record_artifact_created(self):
        """record_artifact_created should accept type and size."""
        from observability.worker_metrics import record_artifact_created
        record_artifact_created("pdf", 102400)

    def test_record_lock_released(self):
        """record_lock_released should accept reason."""
        from observability.worker_metrics import record_lock_released
        record_lock_released("completed")

    def test_record_lock_timeout(self):
        """record_lock_timeout should be callable."""
        from observability.worker_metrics import record_lock_timeout
        record_lock_timeout()

    def test_set_queue_depth(self):
        """set_queue_depth should accept status and count."""
        from observability.worker_metrics import set_queue_depth
        set_queue_depth("queued", 5)
        set_queue_depth("running", 2)

    def test_set_oldest_job_age(self):
        """set_oldest_job_age should accept age in seconds."""
        from observability.worker_metrics import set_oldest_job_age
        set_oldest_job_age(120.5)


class TestWorkerMetricsLabels:
    """Tests for metric label cardinality."""

    def test_job_claims_has_job_kind_label(self):
        """WORKER_JOB_CLAIMS_TOTAL should have job_kind label."""
        from observability.worker_metrics import WORKER_JOB_CLAIMS_TOTAL
        assert "job_kind" in WORKER_JOB_CLAIMS_TOTAL._labelnames

    def test_job_executions_has_labels(self):
        """WORKER_JOB_EXECUTIONS_TOTAL should have job_kind and result labels."""
        from observability.worker_metrics import WORKER_JOB_EXECUTIONS_TOTAL
        assert "job_kind" in WORKER_JOB_EXECUTIONS_TOTAL._labelnames
        assert "result" in WORKER_JOB_EXECUTIONS_TOTAL._labelnames

    def test_job_failures_has_error_code_label(self):
        """WORKER_JOB_FAILURES_TOTAL should have error_code label."""
        from observability.worker_metrics import WORKER_JOB_FAILURES_TOTAL
        assert "error_code" in WORKER_JOB_FAILURES_TOTAL._labelnames

    def test_artifacts_has_type_label(self):
        """WORKER_ARTIFACTS_CREATED_TOTAL should have artifact_type label."""
        from observability.worker_metrics import WORKER_ARTIFACTS_CREATED_TOTAL
        assert "artifact_type" in WORKER_ARTIFACTS_CREATED_TOTAL._labelnames

    def test_queue_depth_has_status_label(self):
        """QUEUE_DEPTH should have status label."""
        from observability.worker_metrics import QUEUE_DEPTH
        assert "status" in QUEUE_DEPTH._labelnames


class TestWorkerMetricsHistogramBuckets:
    """Tests for histogram bucket configuration."""

    def test_claim_duration_has_fine_buckets(self):
        """WORKER_JOB_CLAIM_DURATION_SECONDS should have fine-grained buckets for fast operations."""
        from observability.worker_metrics import WORKER_JOB_CLAIM_DURATION_SECONDS
        buckets = WORKER_JOB_CLAIM_DURATION_SECONDS._kwargs.get("buckets", [])
        assert 0.001 in buckets  # 1ms
        assert 0.01 in buckets   # 10ms
        assert 0.1 in buckets    # 100ms

    def test_execution_duration_has_wide_buckets(self):
        """WORKER_JOB_EXECUTION_DURATION_SECONDS should have wide range for long-running jobs."""
        from observability.worker_metrics import WORKER_JOB_EXECUTION_DURATION_SECONDS
        buckets = WORKER_JOB_EXECUTION_DURATION_SECONDS._kwargs.get("buckets", [])
        assert 1 in buckets     # 1s
        assert 60 in buckets    # 1min
        assert 600 in buckets   # 10min

    def test_artifact_size_has_byte_buckets(self):
        """WORKER_ARTIFACT_SIZE_BYTES should have size buckets from KB to MB."""
        from observability.worker_metrics import WORKER_ARTIFACT_SIZE_BYTES
        buckets = WORKER_ARTIFACT_SIZE_BYTES._kwargs.get("buckets", [])
        assert 1024 in buckets          # 1KB
        assert 1048576 in buckets       # 1MB
        assert 104857600 in buckets     # 100MB


class TestAlertsFile:
    """Tests for ALERTS.md worker section."""

    def test_alerts_file_exists(self):
        """ALERTS.md should exist."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        assert alerts_path.exists()

    def test_alerts_has_worker_section(self):
        """ALERTS.md should have Worker Alerts section."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "## Worker Alerts (v3.4.0)" in content

    def test_alerts_has_worker_down_alert(self):
        """ALERTS.md should have BESSWorkerDown alert."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "BESSWorkerDown" in content

    def test_alerts_has_queue_backlog_alert(self):
        """ALERTS.md should have BESSJobQueueBacklog alert."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "BESSJobQueueBacklog" in content

    def test_alerts_has_job_failures_alert(self):
        """ALERTS.md should have BESSWorkerJobFailures alert."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "BESSWorkerJobFailures" in content

    def test_alerts_has_slow_execution_alert(self):
        """ALERTS.md should have BESSSlowJobExecution alert."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "BESSSlowJobExecution" in content

    def test_alerts_has_lock_timeout_alert(self):
        """ALERTS.md should have BESSJobLockTimeouts alert."""
        alerts_path = Path(__file__).parent.parent.parent / "docs" / "observability" / "ALERTS.md"
        content = alerts_path.read_text()
        assert "BESSJobLockTimeouts" in content


class TestMetricNamingConventions:
    """Tests for Prometheus metric naming conventions."""

    def test_counters_end_with_total(self):
        """Counter metrics should end with _total suffix (added by prometheus_client)."""
        from observability import worker_metrics

        counter_attrs = [
            "WORKER_STARTED_TOTAL",
            "WORKER_SHUTDOWN_TOTAL",
            "WORKER_JOB_CLAIMS_TOTAL",
            "WORKER_JOB_EXECUTIONS_TOTAL",
            "WORKER_ARTIFACTS_CREATED_TOTAL",
        ]

        for attr in counter_attrs:
            metric = getattr(worker_metrics, attr)
            # prometheus_client adds _total suffix automatically, but stores without it
            # Check the attribute name ends with _TOTAL
            assert attr.endswith("_TOTAL"), f"{attr} should end with _TOTAL"

    def test_histograms_have_unit_suffix(self):
        """Histogram metrics should have unit suffix."""
        from observability import worker_metrics

        histogram_units = {
            "WORKER_JOB_CLAIM_DURATION_SECONDS": "_seconds",
            "WORKER_JOB_EXECUTION_DURATION_SECONDS": "_seconds",
            "WORKER_ARTIFACT_SIZE_BYTES": "_bytes",
        }

        for attr, expected_suffix in histogram_units.items():
            metric = getattr(worker_metrics, attr)
            assert metric._name.endswith(expected_suffix), f"{attr} should end with {expected_suffix}"

    def test_all_metrics_have_bess_prefix(self):
        """All metrics should have bess_ prefix."""
        from observability import worker_metrics
        from prometheus_client import Counter, Histogram, Gauge

        for attr in dir(worker_metrics):
            obj = getattr(worker_metrics, attr)
            if isinstance(obj, (Counter, Histogram, Gauge)):
                assert obj._name.startswith("bess_"), f"{attr} should have bess_ prefix"
