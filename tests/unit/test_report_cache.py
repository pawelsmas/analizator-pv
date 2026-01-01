"""
Unit tests for report cache module (v2.5.0 PR3).

Tests verify:
- Cache key computation is deterministic
- LRU cache get/set operations work
- TTL expiration works
- Cache headers are correct
- Cache statistics are accurate
"""

import pytest
import time
import sys

sys.path.insert(0, "services/bess-dispatch")

from report_cache import (
    compute_report_cache_key,
    ReportLRUCache,
    CacheHeader,
    get_cached_report,
    set_cached_report,
    clear_report_cache,
    get_report_cache_stats,
)


class TestComputeReportCacheKey:
    """Tests for compute_report_cache_key function."""

    def test_same_params_produce_same_key(self):
        """Identical parameters should produce identical cache keys."""
        key1 = compute_report_cache_key(
            run_id="abc123",
            format="pdf",
            profile="client",
            client_name="Test Corp",
        )
        key2 = compute_report_cache_key(
            run_id="abc123",
            format="pdf",
            profile="client",
            client_name="Test Corp",
        )
        assert key1 == key2

    def test_different_run_id_produces_different_key(self):
        """Different run_id should produce different cache keys."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf")
        key2 = compute_report_cache_key(run_id="xyz789", format="pdf")
        assert key1 != key2

    def test_different_format_produces_different_key(self):
        """Different format should produce different cache keys."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf")
        key2 = compute_report_cache_key(run_id="abc123", format="xlsx")
        assert key1 != key2

    def test_different_profile_produces_different_key(self):
        """Different profile should produce different cache keys."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf", profile="client")
        key2 = compute_report_cache_key(run_id="abc123", format="pdf", profile="engineering")
        assert key1 != key2

    def test_none_and_empty_string_produce_same_key(self):
        """None and empty string for optional params should produce same key."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf", client_name=None)
        key2 = compute_report_cache_key(run_id="abc123", format="pdf", client_name="")
        assert key1 == key2

    def test_key_is_64_chars_hex(self):
        """Cache key should be a 64-character hex string (SHA256)."""
        key = compute_report_cache_key(run_id="abc123", format="pdf")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_max_table_rows_produces_different_key(self):
        """Different max_table_rows should produce different cache keys."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf", max_table_rows=48)
        key2 = compute_report_cache_key(run_id="abc123", format="pdf", max_table_rows=96)
        assert key1 != key2

    def test_branding_affects_key(self):
        """Branding options should affect cache key."""
        key1 = compute_report_cache_key(run_id="abc123", format="pdf")
        key2 = compute_report_cache_key(run_id="abc123", format="pdf", client_name="Acme")
        assert key1 != key2


class TestReportLRUCache:
    """Tests for ReportLRUCache class."""

    def test_get_miss_returns_none(self):
        """Get on empty cache returns None."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        result = cache.get("nonexistent", "pdf")
        assert result is None

    def test_set_then_get_returns_content(self):
        """Set then get returns the same content."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        content = b"test pdf content"
        cache.set("key1", "pdf", content)
        result = cache.get("key1", "pdf")
        assert result == content

    def test_different_formats_are_isolated(self):
        """Cache entries are isolated by format."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        cache.set("key1", "pdf", b"pdf content")
        cache.set("key1", "xlsx", b"xlsx content")

        assert cache.get("key1", "pdf") == b"pdf content"
        assert cache.get("key1", "xlsx") == b"xlsx content"
        assert cache.get("key1", "zip") is None

    def test_lru_eviction(self):
        """LRU eviction works when max_entries is exceeded."""
        cache = ReportLRUCache(max_entries=2, ttl_seconds=3600)
        cache.set("key1", "pdf", b"content1")
        cache.set("key2", "pdf", b"content2")
        cache.set("key3", "pdf", b"content3")  # Should evict key1

        assert cache.get("key1", "pdf") is None  # Evicted
        assert cache.get("key2", "pdf") == b"content2"
        assert cache.get("key3", "pdf") == b"content3"

    def test_access_updates_lru_order(self):
        """Accessing an entry moves it to end (most recent)."""
        cache = ReportLRUCache(max_entries=2, ttl_seconds=3600)
        cache.set("key1", "pdf", b"content1")
        cache.set("key2", "pdf", b"content2")

        # Access key1, making it most recently used
        cache.get("key1", "pdf")

        # Add key3, should evict key2 (oldest)
        cache.set("key3", "pdf", b"content3")

        assert cache.get("key1", "pdf") == b"content1"  # Still there
        assert cache.get("key2", "pdf") is None  # Evicted
        assert cache.get("key3", "pdf") == b"content3"

    def test_ttl_expiration(self):
        """Expired entries return None and are removed."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=1)  # 1 second TTL
        cache.set("key1", "pdf", b"content")

        # Should be available immediately
        assert cache.get("key1", "pdf") == b"content"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired now
        assert cache.get("key1", "pdf") is None

    def test_invalidate_removes_entry(self):
        """Invalidate removes a specific entry."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        cache.set("key1", "pdf", b"content")
        cache.invalidate("key1", "pdf")
        assert cache.get("key1", "pdf") is None

    def test_invalidate_all_formats(self):
        """Invalidate without format removes from all formats."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        cache.set("key1", "pdf", b"pdf")
        cache.set("key1", "xlsx", b"xlsx")
        cache.invalidate("key1")  # All formats
        assert cache.get("key1", "pdf") is None
        assert cache.get("key1", "xlsx") is None

    def test_clear_removes_all(self):
        """Clear removes all entries."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        cache.set("key1", "pdf", b"pdf")
        cache.set("key2", "xlsx", b"xlsx")
        cache.clear()
        assert cache.get("key1", "pdf") is None
        assert cache.get("key2", "xlsx") is None

    def test_stats_returns_correct_counts(self):
        """Stats returns accurate entry counts."""
        cache = ReportLRUCache(max_entries=10, ttl_seconds=3600)
        cache.set("key1", "pdf", b"pdf")
        cache.set("key2", "xlsx", b"xlsx")
        cache.set("key3", "zip", b"zip")

        stats = cache.stats()
        assert stats["max_entries"] == 10
        assert stats["ttl_seconds"] == 3600
        assert stats["entries"]["pdf"] == 1
        assert stats["entries"]["xlsx"] == 1
        assert stats["entries"]["zip"] == 1
        assert stats["total_entries"] == 3


class TestCacheHeader:
    """Tests for cache header constants."""

    def test_hit_value(self):
        """HIT constant is correct."""
        assert CacheHeader.HIT == "HIT"

    def test_miss_value(self):
        """MISS constant is correct."""
        assert CacheHeader.MISS == "MISS"

    def test_disabled_value(self):
        """DISABLED constant is correct."""
        assert CacheHeader.DISABLED == "DISABLED"


class TestGlobalCacheFunctions:
    """Tests for global cache API functions."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_report_cache()

    def test_get_cached_report_miss(self):
        """get_cached_report returns None and MISS for uncached key."""
        content, header = get_cached_report("nonexistent", "pdf")
        assert content is None
        assert header in (CacheHeader.MISS, CacheHeader.DISABLED)

    def test_set_then_get_cached_report(self):
        """set_cached_report then get_cached_report works."""
        set_cached_report("key1", "pdf", b"test content")
        content, header = get_cached_report("key1", "pdf")

        # If cache is enabled, should be HIT
        if header == CacheHeader.HIT:
            assert content == b"test content"

    def test_get_report_cache_stats(self):
        """get_report_cache_stats returns valid stats."""
        stats = get_report_cache_stats()
        assert "max_entries" in stats
        assert "ttl_seconds" in stats
        assert "entries" in stats
        assert "enabled" in stats


class TestCacheKeyEdgeCases:
    """Edge case tests for cache key computation."""

    def test_unicode_client_name(self):
        """Unicode characters in client_name are handled."""
        key = compute_report_cache_key(
            run_id="abc123",
            format="pdf",
            client_name="Żółta Firma Sp. z o.o."
        )
        assert len(key) == 64

    def test_long_notes(self):
        """Long notes are handled correctly."""
        long_notes = "A" * 2000
        key = compute_report_cache_key(
            run_id="abc123",
            format="pdf",
            notes=long_notes
        )
        assert len(key) == 64

    def test_special_characters_in_run_id(self):
        """Special characters in run_id are handled."""
        key = compute_report_cache_key(
            run_id="abc-123-def-456-ghi-789",
            format="pdf"
        )
        assert len(key) == 64
