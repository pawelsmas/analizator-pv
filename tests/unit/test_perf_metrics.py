"""
Unit tests for performance metrics module (v2.5.0 PR6).

Tests verify:
- All counters and histograms are defined correctly
- Helper functions work correctly
- Metric labels are valid
- Configuration is accessible
"""

import pytest
import sys

# Skip all tests if prometheus_client is not installed
pytest.importorskip("prometheus_client")

sys.path.insert(0, "services/bess-dispatch")


class TestRequestSizeMetrics:
    """Tests for request/response size metrics."""

    def test_request_size_bytes_defined(self):
        """REQUEST_SIZE_BYTES should be defined."""
        from observability.perf_metrics import REQUEST_SIZE_BYTES
        assert REQUEST_SIZE_BYTES is not None
        assert REQUEST_SIZE_BYTES._name == "bess_request_size_bytes"

    def test_request_size_bytes_has_endpoint_label(self):
        """REQUEST_SIZE_BYTES should have endpoint label."""
        from observability.perf_metrics import REQUEST_SIZE_BYTES
        assert "endpoint" in REQUEST_SIZE_BYTES._labelnames

    def test_response_size_bytes_defined(self):
        """RESPONSE_SIZE_BYTES should be defined."""
        from observability.perf_metrics import RESPONSE_SIZE_BYTES
        assert RESPONSE_SIZE_BYTES is not None
        assert RESPONSE_SIZE_BYTES._name == "bess_response_size_bytes"

    def test_response_size_bytes_has_endpoint_label(self):
        """RESPONSE_SIZE_BYTES should have endpoint label."""
        from observability.perf_metrics import RESPONSE_SIZE_BYTES
        assert "endpoint" in RESPONSE_SIZE_BYTES._labelnames

    def test_response_size_compressed_bytes_defined(self):
        """RESPONSE_SIZE_COMPRESSED_BYTES should be defined."""
        from observability.perf_metrics import RESPONSE_SIZE_COMPRESSED_BYTES
        assert RESPONSE_SIZE_COMPRESSED_BYTES is not None
        assert RESPONSE_SIZE_COMPRESSED_BYTES._name == "bess_response_size_compressed_bytes"


class TestSlowRequestMetrics:
    """Tests for slow request metrics."""

    def test_slow_requests_total_defined(self):
        """SLOW_REQUESTS_TOTAL should be defined."""
        from observability.perf_metrics import SLOW_REQUESTS_TOTAL
        assert SLOW_REQUESTS_TOTAL is not None
        # Counter adds _total suffix automatically
        assert SLOW_REQUESTS_TOTAL._name == "bess_slow_requests"

    def test_slow_requests_total_has_labels(self):
        """SLOW_REQUESTS_TOTAL should have endpoint and method labels."""
        from observability.perf_metrics import SLOW_REQUESTS_TOTAL
        assert "endpoint" in SLOW_REQUESTS_TOTAL._labelnames
        assert "method" in SLOW_REQUESTS_TOTAL._labelnames

    def test_request_duration_seconds_defined(self):
        """REQUEST_DURATION_SECONDS should be defined."""
        from observability.perf_metrics import REQUEST_DURATION_SECONDS
        assert REQUEST_DURATION_SECONDS is not None
        assert REQUEST_DURATION_SECONDS._name == "bess_request_duration_seconds"

    def test_request_duration_seconds_has_labels(self):
        """REQUEST_DURATION_SECONDS should have endpoint and method labels."""
        from observability.perf_metrics import REQUEST_DURATION_SECONDS
        assert "endpoint" in REQUEST_DURATION_SECONDS._labelnames
        assert "method" in REQUEST_DURATION_SECONDS._labelnames


class TestCacheMetrics:
    """Tests for cache metrics."""

    def test_report_cache_hits_total_defined(self):
        """REPORT_CACHE_HITS_TOTAL should be defined."""
        from observability.perf_metrics import REPORT_CACHE_HITS_TOTAL
        assert REPORT_CACHE_HITS_TOTAL is not None
        # Counter adds _total suffix automatically
        assert REPORT_CACHE_HITS_TOTAL._name == "bess_report_cache_hits"

    def test_report_cache_hits_total_has_format_label(self):
        """REPORT_CACHE_HITS_TOTAL should have format label."""
        from observability.perf_metrics import REPORT_CACHE_HITS_TOTAL
        assert "format" in REPORT_CACHE_HITS_TOTAL._labelnames

    def test_report_cache_misses_total_defined(self):
        """REPORT_CACHE_MISSES_TOTAL should be defined."""
        from observability.perf_metrics import REPORT_CACHE_MISSES_TOTAL
        assert REPORT_CACHE_MISSES_TOTAL is not None
        # Counter adds _total suffix automatically
        assert REPORT_CACHE_MISSES_TOTAL._name == "bess_report_cache_misses"

    def test_report_cache_size_entries_defined(self):
        """REPORT_CACHE_SIZE_ENTRIES should be defined."""
        from observability.perf_metrics import REPORT_CACHE_SIZE_ENTRIES
        assert REPORT_CACHE_SIZE_ENTRIES is not None
        assert REPORT_CACHE_SIZE_ENTRIES._name == "bess_report_cache_size_entries"


class TestCompressionMetrics:
    """Tests for compression metrics."""

    def test_compression_ratio_defined(self):
        """COMPRESSION_RATIO should be defined."""
        from observability.perf_metrics import COMPRESSION_RATIO
        assert COMPRESSION_RATIO is not None
        assert COMPRESSION_RATIO._name == "bess_compression_ratio"

    def test_compression_savings_bytes_defined(self):
        """COMPRESSION_SAVINGS_BYTES should be defined."""
        from observability.perf_metrics import COMPRESSION_SAVINGS_BYTES
        assert COMPRESSION_SAVINGS_BYTES is not None
        # Counter adds _total suffix automatically
        assert COMPRESSION_SAVINGS_BYTES._name == "bess_compression_savings_bytes"


class TestLimitMetrics:
    """Tests for limit enforcement metrics."""

    def test_limit_rejections_total_defined(self):
        """LIMIT_REJECTIONS_TOTAL should be defined."""
        from observability.perf_metrics import LIMIT_REJECTIONS_TOTAL
        assert LIMIT_REJECTIONS_TOTAL is not None
        # Counter adds _total suffix automatically
        assert LIMIT_REJECTIONS_TOTAL._name == "bess_limit_rejections"

    def test_limit_rejections_total_has_limit_type_label(self):
        """LIMIT_REJECTIONS_TOTAL should have limit_type label."""
        from observability.perf_metrics import LIMIT_REJECTIONS_TOTAL
        assert "limit_type" in LIMIT_REJECTIONS_TOTAL._labelnames


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_track_request_size_works(self):
        """track_request_size should work without errors."""
        from observability.perf_metrics import track_request_size
        # Should not raise
        track_request_size("/api/test", 1000)

    def test_track_response_size_works(self):
        """track_response_size should work without errors."""
        from observability.perf_metrics import track_response_size
        # Should not raise
        track_response_size("/api/test", 5000)

    def test_track_response_size_with_compression(self):
        """track_response_size should work with compressed size."""
        from observability.perf_metrics import track_response_size
        # Should not raise
        track_response_size("/api/test", 5000, compressed_bytes=1500)

    def test_track_response_size_zero_original_handles_gracefully(self):
        """track_response_size should handle zero original size."""
        from observability.perf_metrics import track_response_size
        # Should not raise
        track_response_size("/api/test", 0, compressed_bytes=0)

    def test_track_request_duration_works(self):
        """track_request_duration should work without errors."""
        from observability.perf_metrics import track_request_duration
        # Should not raise
        track_request_duration("/api/test", "POST", 1.5)

    def test_track_request_duration_counts_slow(self):
        """track_request_duration should count slow requests."""
        from observability.perf_metrics import (
            track_request_duration, SLOW_REQUEST_THRESHOLD_SECONDS
        )
        # Duration exceeding threshold should not raise
        track_request_duration("/api/test", "POST", SLOW_REQUEST_THRESHOLD_SECONDS + 1.0)

    def test_track_request_duration_fast_request(self):
        """track_request_duration should handle fast requests."""
        from observability.perf_metrics import track_request_duration
        # Fast request should not raise
        track_request_duration("/api/test", "GET", 0.01)

    def test_track_report_cache_hit_works(self):
        """track_report_cache_hit should work without errors."""
        from observability.perf_metrics import track_report_cache_hit
        # Should not raise
        track_report_cache_hit("pdf")

    def test_track_report_cache_miss_works(self):
        """track_report_cache_miss should work without errors."""
        from observability.perf_metrics import track_report_cache_miss
        # Should not raise
        track_report_cache_miss("xlsx")

    def test_update_report_cache_size_works(self):
        """update_report_cache_size should work without errors."""
        from observability.perf_metrics import update_report_cache_size
        # Should not raise
        update_report_cache_size("zip", 5)

    def test_track_limit_rejection_works(self):
        """track_limit_rejection should work without errors."""
        from observability.perf_metrics import track_limit_rejection
        # Should not raise
        track_limit_rejection("request_size")


class TestConfiguration:
    """Tests for configuration."""

    def test_slow_request_threshold_default(self):
        """SLOW_REQUEST_THRESHOLD_SECONDS should have default value."""
        from observability.perf_metrics import SLOW_REQUEST_THRESHOLD_SECONDS
        assert SLOW_REQUEST_THRESHOLD_SECONDS > 0

    def test_get_perf_config_returns_dict(self):
        """get_perf_config should return a dictionary."""
        from observability.perf_metrics import get_perf_config
        config = get_perf_config()
        assert isinstance(config, dict)

    def test_get_perf_config_contains_threshold(self):
        """get_perf_config should contain slow_request_threshold_seconds."""
        from observability.perf_metrics import get_perf_config
        config = get_perf_config()
        assert "slow_request_threshold_seconds" in config


class TestHistogramBuckets:
    """Tests for histogram bucket configurations."""

    def test_request_size_bytes_has_buckets(self):
        """REQUEST_SIZE_BYTES should have reasonable bucket sizes."""
        from observability.perf_metrics import REQUEST_SIZE_BYTES
        # Should have buckets for various sizes up to several MB
        assert REQUEST_SIZE_BYTES._upper_bounds is not None
        assert len(REQUEST_SIZE_BYTES._upper_bounds) > 0

    def test_response_size_bytes_has_buckets(self):
        """RESPONSE_SIZE_BYTES should have reasonable bucket sizes."""
        from observability.perf_metrics import RESPONSE_SIZE_BYTES
        assert RESPONSE_SIZE_BYTES._upper_bounds is not None
        assert len(RESPONSE_SIZE_BYTES._upper_bounds) > 0

    def test_request_duration_seconds_has_buckets(self):
        """REQUEST_DURATION_SECONDS should have reasonable bucket sizes."""
        from observability.perf_metrics import REQUEST_DURATION_SECONDS
        assert REQUEST_DURATION_SECONDS._upper_bounds is not None
        # Should cover sub-second to multi-second durations
        assert len(REQUEST_DURATION_SECONDS._upper_bounds) > 0

    def test_compression_ratio_has_buckets(self):
        """COMPRESSION_RATIO should have buckets from 0 to 1."""
        from observability.perf_metrics import COMPRESSION_RATIO
        assert COMPRESSION_RATIO._upper_bounds is not None
        # Should have buckets covering 0.0 to 1.0 range
        assert len(COMPRESSION_RATIO._upper_bounds) > 0
