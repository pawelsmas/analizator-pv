"""
Unit tests for wait_http utility (v2.6.0 PR3).

Tests verify:
- URL parsing works correctly
- Endpoint checking logic
"""

import sys

import pytest

sys.path.insert(0, "scripts/dev")

from wait_http import parse_url, check_endpoint


class TestParseUrl:
    """Tests for parse_url function."""

    def test_parse_simple_url(self):
        """Parse simple localhost URL."""
        result = parse_url("http://localhost:8031/health")
        assert result["scheme"] == "http"
        assert result["host"] == "localhost"
        assert result["port"] == 8031
        assert result["path"] == "/health"

    def test_parse_url_no_port(self):
        """Parse URL without explicit port."""
        result = parse_url("http://example.com/api")
        assert result["scheme"] == "http"
        assert result["host"] == "example.com"
        assert result["port"] == 80
        assert result["path"] == "/api"

    def test_parse_https_url(self):
        """Parse HTTPS URL."""
        result = parse_url("https://example.com/health")
        assert result["scheme"] == "https"
        assert result["port"] == 443

    def test_parse_url_preserves_original(self):
        """Original URL is preserved."""
        url = "http://localhost:8031/version"
        result = parse_url(url)
        assert result["url"] == url

    def test_parse_url_with_path_only(self):
        """Parse URL with just path."""
        result = parse_url("http://localhost/")
        assert result["path"] == "/"


class TestCheckEndpoint:
    """Tests for check_endpoint function (non-network)."""

    def test_check_invalid_url_returns_error(self):
        """Invalid URL should return error."""
        success, message = check_endpoint("not-a-valid-url")
        assert success is False
        assert "error" in message.lower() or "Error" in message

    def test_check_unreachable_returns_error(self):
        """Unreachable host should return connection error."""
        # Using a port that should not be listening
        success, message = check_endpoint("http://localhost:59999/health")
        assert success is False
        # Should be connection error or similar


class TestCheckEndpointEdgeCases:
    """Edge case tests."""

    def test_empty_url_fails(self):
        """Empty URL should fail."""
        success, message = check_endpoint("")
        assert success is False
