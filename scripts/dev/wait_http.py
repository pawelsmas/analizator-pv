#!/usr/bin/env python3
"""
HTTP Wait Utility (v2.6.0 PR3).

Waits for an HTTP endpoint to become available, with timeout.
Cross-platform replacement for bash-based wait loops.

Usage:
    python scripts/dev/wait_http.py http://localhost:8031/health
    python scripts/dev/wait_http.py http://localhost:8031/health --timeout 60
    python scripts/dev/wait_http.py http://localhost:8031/version --expect-json

Exit codes:
    0 - Endpoint responded successfully
    1 - Timeout or error
"""

import argparse
import json
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


def parse_url(url: str) -> dict:
    """Parse URL into components."""
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme or "http",
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (443 if parsed.scheme == "https" else 80),
        "path": parsed.path or "/",
        "url": url,
    }


def check_endpoint(url: str, expect_json: bool = False) -> tuple:
    """
    Check if endpoint is available.

    Returns:
        (success: bool, message: str)
    """
    try:
        req = Request(url, headers={"User-Agent": "wait_http/1.0"})
        with urlopen(req, timeout=5) as response:
            status = response.status
            content = response.read().decode("utf-8", errors="replace")

            if status >= 200 and status < 400:
                if expect_json:
                    try:
                        json.loads(content)
                        return True, f"OK (status {status}, valid JSON)"
                    except json.JSONDecodeError:
                        return False, f"Response is not valid JSON"
                return True, f"OK (status {status})"
            else:
                return False, f"Status {status}"
    except HTTPError as e:
        return False, f"HTTP error {e.code}"
    except URLError as e:
        return False, f"Connection error: {e.reason}"
    except TimeoutError:
        return False, "Request timeout"
    except Exception as e:
        return False, f"Error: {e}"


def wait_for_endpoint(
    url: str,
    timeout: int = 120,
    interval: int = 2,
    expect_json: bool = False,
    quiet: bool = False,
) -> bool:
    """
    Wait for HTTP endpoint to become available.

    Args:
        url: URL to check
        timeout: Maximum wait time in seconds
        interval: Check interval in seconds
        expect_json: Expect valid JSON response
        quiet: Suppress output

    Returns:
        True if endpoint became available, False on timeout
    """
    parsed = parse_url(url)

    if not quiet:
        print(f"Waiting for {url}...")

    start = time.time()
    attempts = 0

    while time.time() - start < timeout:
        attempts += 1
        success, message = check_endpoint(url, expect_json)

        if success:
            elapsed = time.time() - start
            if not quiet:
                print(f"[OK] {url} is ready ({elapsed:.1f}s, {attempts} attempts)")
            return True

        if not quiet:
            elapsed = time.time() - start
            remaining = timeout - elapsed
            print(f"  Attempt {attempts}: {message} (waiting {remaining:.0f}s more)")

        time.sleep(interval)

    if not quiet:
        print(f"[FAIL] Timeout waiting for {url} after {timeout}s")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Wait for HTTP endpoint to become available"
    )
    parser.add_argument(
        "url",
        help="URL to check (e.g., http://localhost:8031/health)",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=120,
        help="Maximum wait time in seconds (default: 120)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=2,
        help="Check interval in seconds (default: 2)",
    )
    parser.add_argument(
        "--expect-json",
        action="store_true",
        help="Expect valid JSON response",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress output",
    )

    args = parser.parse_args()

    success = wait_for_endpoint(
        url=args.url,
        timeout=args.timeout,
        interval=args.interval,
        expect_json=args.expect_json,
        quiet=args.quiet,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
