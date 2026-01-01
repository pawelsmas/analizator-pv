"""
Unit tests for benchmark harness (v2.5.0 PR5).

Tests verify:
- BenchmarkResult calculations are correct
- Sizing request generators work
- Result serialization works
"""

import pytest
import sys

sys.path.insert(0, "scripts")

from bench_api import (
    BenchmarkResult,
    sizing_request_24h,
    sizing_request_week,
)


class TestBenchmarkResult:
    """Tests for BenchmarkResult dataclass."""

    def test_p50_single_value(self):
        """p50 with single value returns that value."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=1,
            success_count=1,
            failure_count=0,
            latencies_ms=[100.0],
            response_sizes_bytes=[1000],
        )
        assert result.p50_ms == 100.0

    def test_p50_multiple_values(self):
        """p50 returns median for multiple values."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[10, 20, 30, 40, 50],
            response_sizes_bytes=[1000] * 5,
        )
        assert result.p50_ms == 30.0

    def test_p95_requires_multiple_values(self):
        """p95 falls back to p50 for small samples."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=1,
            success_count=1,
            failure_count=0,
            latencies_ms=[100.0],
            response_sizes_bytes=[1000],
        )
        assert result.p95_ms == result.p50_ms

    def test_p99_requires_many_values(self):
        """p99 falls back to p95 for small samples."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[10, 20, 30, 40, 50],
            response_sizes_bytes=[1000] * 5,
        )
        assert result.p99_ms == result.p95_ms

    def test_max_ms(self):
        """max_ms returns maximum latency."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[10, 20, 300, 40, 50],
            response_sizes_bytes=[1000] * 5,
        )
        assert result.max_ms == 300

    def test_min_ms(self):
        """min_ms returns minimum latency."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[10, 20, 300, 40, 50],
            response_sizes_bytes=[1000] * 5,
        )
        assert result.min_ms == 10

    def test_avg_ms(self):
        """avg_ms returns average latency."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[100, 100, 100, 100, 100],
            response_sizes_bytes=[1000] * 5,
        )
        assert result.avg_ms == 100.0

    def test_success_rate_all_success(self):
        """success_rate returns 1.0 for all successes."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=10,
            success_count=10,
            failure_count=0,
            latencies_ms=[100] * 10,
            response_sizes_bytes=[1000] * 10,
        )
        assert result.success_rate == 1.0

    def test_success_rate_half_failures(self):
        """success_rate returns 0.5 for half failures."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=10,
            success_count=5,
            failure_count=5,
            latencies_ms=[100] * 5,
            response_sizes_bytes=[1000] * 5,
        )
        assert result.success_rate == 0.5

    def test_avg_response_size(self):
        """avg_response_size_bytes returns average."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=3,
            success_count=3,
            failure_count=0,
            latencies_ms=[100, 100, 100],
            response_sizes_bytes=[1000, 2000, 3000],
        )
        assert result.avg_response_size_bytes == 2000.0

    def test_requests_per_second(self):
        """requests_per_second is calculated correctly."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=10,
            success_count=10,
            failure_count=0,
            latencies_ms=[100] * 10,  # 100ms each = 1 second total
            response_sizes_bytes=[1000] * 10,
        )
        # 10 requests / 1 second = 10 req/s
        assert result.requests_per_second == 10.0

    def test_to_dict_contains_all_fields(self):
        """to_dict returns dict with all expected fields."""
        result = BenchmarkResult(
            endpoint="/test",
            method="POST",
            iterations=5,
            success_count=5,
            failure_count=0,
            latencies_ms=[100, 110, 120, 130, 140],
            response_sizes_bytes=[1000] * 5,
        )
        d = result.to_dict()

        assert d["endpoint"] == "/test"
        assert d["method"] == "POST"
        assert d["iterations"] == 5
        assert "latency_ms" in d
        assert "p50" in d["latency_ms"]
        assert "p95" in d["latency_ms"]
        assert "p99" in d["latency_ms"]
        assert "throughput" in d
        assert "requests_per_second" in d["throughput"]

    def test_empty_latencies_returns_zero(self):
        """Empty latencies returns 0 for all metrics."""
        result = BenchmarkResult(
            endpoint="/test",
            method="GET",
            iterations=0,
            success_count=0,
            failure_count=0,
            latencies_ms=[],
            response_sizes_bytes=[],
        )
        assert result.p50_ms == 0.0
        assert result.max_ms == 0.0
        assert result.min_ms == 0.0
        assert result.avg_ms == 0.0


class TestSizingRequestGenerators:
    """Tests for sizing request generator functions."""

    def test_sizing_request_24h_has_24_steps(self):
        """sizing_request_24h generates 24 steps."""
        req = sizing_request_24h()
        assert len(req["load_kw"]) == 24
        assert len(req["pv_generation_kw"]) == 24

    def test_sizing_request_24h_has_required_fields(self):
        """sizing_request_24h has all required fields."""
        req = sizing_request_24h()
        assert "load_kw" in req
        assert "pv_generation_kw" in req
        assert "mode" in req
        assert "durations_h" in req
        assert "interval_minutes" in req
        assert "discount_rate" in req

    def test_sizing_request_week_has_168_steps(self):
        """sizing_request_week generates 168 steps (7 days)."""
        req = sizing_request_week()
        assert len(req["load_kw"]) == 168
        assert len(req["pv_generation_kw"]) == 168

    def test_sizing_request_week_has_more_durations(self):
        """sizing_request_week has 3 duration variants."""
        req = sizing_request_week()
        assert len(req["durations_h"]) == 3
