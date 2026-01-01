"""
Unit tests for compression helper module (v2.5.0 PR4).

Tests verify:
- GZip compression and decompression
- Accept-Encoding header parsing
- Compression threshold logic
- Content type filtering
"""

import pytest
import gzip
import sys

sys.path.insert(0, "services/bess-dispatch")

from compression_helper import (
    accepts_gzip,
    compress_content,
    decompress_content,
    should_compress,
    compress_response,
    get_compression_stats,
    COMPRESSION_THRESHOLD_BYTES,
    COMPRESSION_LEVEL,
)


class TestAcceptsGzip:
    """Tests for accepts_gzip function."""

    def test_gzip_only(self):
        """'gzip' should return True."""
        assert accepts_gzip("gzip") is True

    def test_gzip_with_others(self):
        """'gzip, deflate' should return True."""
        assert accepts_gzip("gzip, deflate") is True

    def test_deflate_without_gzip(self):
        """'deflate' should return False."""
        assert accepts_gzip("deflate") is False

    def test_gzip_with_quality(self):
        """'gzip;q=1.0, identity;q=0.5' should return True."""
        assert accepts_gzip("gzip;q=1.0, identity;q=0.5") is True

    def test_wildcard_accepts_gzip(self):
        """'*' should return True (accepts any)."""
        assert accepts_gzip("*") is True

    def test_empty_string(self):
        """Empty string should return False."""
        assert accepts_gzip("") is False

    def test_none(self):
        """None should return False."""
        assert accepts_gzip(None) is False

    def test_case_insensitive(self):
        """'GZIP' should return True (case insensitive)."""
        assert accepts_gzip("GZIP") is True

    def test_gzip_with_spaces(self):
        """' gzip , deflate ' should return True."""
        assert accepts_gzip(" gzip , deflate ") is True


class TestCompressDecompress:
    """Tests for compress_content and decompress_content."""

    def test_compress_small_content(self):
        """Small content should compress."""
        content = b"Hello, World!"
        compressed = compress_content(content)
        assert len(compressed) > 0
        assert compressed != content

    def test_compress_large_json(self):
        """Large JSON should compress significantly."""
        import json
        data = {"items": [{"id": i, "name": f"Item {i}"} for i in range(1000)]}
        content = json.dumps(data).encode("utf-8")
        compressed = compress_content(content)
        # Should compress to less than 30% of original
        assert len(compressed) < len(content) * 0.3

    def test_decompress_matches_original(self):
        """Decompressed content should match original."""
        content = b"Test content for compression and decompression"
        compressed = compress_content(content)
        decompressed = decompress_content(compressed)
        assert decompressed == content

    def test_compress_with_custom_level(self):
        """Custom compression level should work."""
        content = b"x" * 10000
        compressed_1 = compress_content(content, level=1)
        compressed_9 = compress_content(content, level=9)
        # Higher level should compress more (but slower)
        assert len(compressed_9) <= len(compressed_1)

    def test_compress_empty_content(self):
        """Empty content should compress."""
        compressed = compress_content(b"")
        assert len(compressed) > 0
        assert decompress_content(compressed) == b""

    def test_compress_binary_content(self):
        """Binary content should compress."""
        content = bytes(range(256)) * 100
        compressed = compress_content(content)
        assert decompress_content(compressed) == content


class TestShouldCompress:
    """Tests for should_compress function."""

    def test_json_above_threshold_with_gzip(self):
        """JSON above threshold with gzip accept should compress."""
        result = should_compress(
            content_type="application/json",
            content_length=COMPRESSION_THRESHOLD_BYTES + 1000,
            accept_encoding="gzip",
        )
        assert result is True

    def test_json_below_threshold(self):
        """JSON below threshold should not compress."""
        result = should_compress(
            content_type="application/json",
            content_length=100,  # Below threshold
            accept_encoding="gzip",
        )
        assert result is False

    def test_json_without_gzip_accept(self):
        """JSON without gzip accept should not compress."""
        result = should_compress(
            content_type="application/json",
            content_length=10000,
            accept_encoding="deflate",
        )
        assert result is False

    def test_non_compressible_type(self):
        """Non-compressible content type should not compress."""
        result = should_compress(
            content_type="image/png",
            content_length=10000,
            accept_encoding="gzip",
        )
        assert result is False

    def test_json_with_charset(self):
        """JSON with charset should compress."""
        result = should_compress(
            content_type="application/json; charset=utf-8",
            content_length=10000,
            accept_encoding="gzip",
        )
        assert result is True

    def test_text_plain_compresses(self):
        """text/plain should be compressible."""
        result = should_compress(
            content_type="text/plain",
            content_length=10000,
            accept_encoding="gzip",
        )
        assert result is True

    def test_none_content_type(self):
        """None content type should not compress."""
        result = should_compress(
            content_type=None,
            content_length=10000,
            accept_encoding="gzip",
        )
        assert result is False


class TestCompressResponse:
    """Tests for compress_response function."""

    def test_compresses_large_json(self):
        """Large JSON with gzip accept should compress."""
        content = b'{"data": ' + b'"x"' * 5000 + b'}'
        compressed, headers = compress_response(
            content=content,
            content_type="application/json",
            accept_encoding="gzip",
        )
        assert len(compressed) < len(content)
        assert headers.get("Content-Encoding") == "gzip"
        assert headers.get("Vary") == "Accept-Encoding"

    def test_skips_small_content(self):
        """Small content should not compress."""
        content = b'{"ok": true}'
        result, headers = compress_response(
            content=content,
            content_type="application/json",
            accept_encoding="gzip",
        )
        assert result == content
        assert "Content-Encoding" not in headers

    def test_skips_without_accept(self):
        """Without gzip accept should not compress."""
        content = b'x' * 10000
        result, headers = compress_response(
            content=content,
            content_type="application/json",
            accept_encoding="",
        )
        assert result == content
        assert "Content-Encoding" not in headers


class TestGetCompressionStats:
    """Tests for get_compression_stats function."""

    def test_returns_dict(self):
        """Should return a dict with configuration."""
        stats = get_compression_stats()
        assert isinstance(stats, dict)
        assert "enabled" in stats
        assert "threshold_bytes" in stats
        assert "level" in stats
        assert "compressible_types" in stats

    def test_threshold_matches_config(self):
        """Threshold should match COMPRESSION_THRESHOLD_BYTES."""
        stats = get_compression_stats()
        assert stats["threshold_bytes"] == COMPRESSION_THRESHOLD_BYTES

    def test_level_matches_config(self):
        """Level should match COMPRESSION_LEVEL."""
        stats = get_compression_stats()
        assert stats["level"] == COMPRESSION_LEVEL

    def test_json_in_compressible_types(self):
        """application/json should be in compressible types."""
        stats = get_compression_stats()
        assert "application/json" in stats["compressible_types"]
