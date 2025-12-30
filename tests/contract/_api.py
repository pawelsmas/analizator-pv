"""
Shared helpers for contract tests.

Provides:
- post_json(): POST request with error handling
- get_json(): GET request with error handling
- load_smoke_payload(): Load JSON payload from scripts/smoke/
- pick_recommended_variant(): Extract recommended variant from sizing response
"""
import os
import json
import requests
from pathlib import Path
from typing import Any, Dict

DEFAULT_BASE_URL = (
    os.getenv("BASE_URL")
    or os.getenv("API_BASE_URL")
    or os.getenv("BESS_DISPATCH_URL")
    or "http://localhost:8031"
)


def post_json(path: str, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    """
    POST JSON payload to API endpoint.

    Args:
        path: API path (e.g., "/sizing")
        payload: JSON-serializable dict
        timeout: Request timeout in seconds

    Returns:
        Response JSON as dict

    Raises:
        AssertionError: If response status >= 400
    """
    url = DEFAULT_BASE_URL.rstrip("/") + path
    r = requests.post(url, json=payload, timeout=timeout)
    # In contract tests we want to see body when something fails
    if r.status_code >= 400:
        raise AssertionError(f"POST {path} -> {r.status_code}\n{r.text[:2000]}")
    return r.json()


def get_json(path: str, timeout: int = 30) -> Dict[str, Any]:
    """
    GET JSON from API endpoint.

    Args:
        path: API path (e.g., "/runs/abc123")
        timeout: Request timeout in seconds

    Returns:
        Response JSON as dict

    Raises:
        AssertionError: If response status >= 400
    """
    url = DEFAULT_BASE_URL.rstrip("/") + path
    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise AssertionError(f"GET {path} -> {r.status_code}\n{r.text[:2000]}")
    return r.json()


def load_smoke_payload(name: str) -> Dict[str, Any]:
    """
    Load JSON payload from scripts/smoke/ directory.

    Args:
        name: Filename (e.g., "sizing_stacked_no_arbitrage.json")

    Returns:
        Parsed JSON as dict
    """
    # Try relative path from repo root
    p = Path("scripts/smoke") / name
    if not p.exists():
        # Try from tests/contract directory
        p = Path(__file__).parent.parent.parent / "scripts" / "smoke" / name
    return json.loads(p.read_text(encoding="utf-8"))


def pick_recommended_variant(resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract recommended variant from sizing response.

    Args:
        resp: Full sizing API response

    Returns:
        Recommended variant dict, or first variant if none marked recommended

    Raises:
        AssertionError: If response has no variants
    """
    variants = resp.get("variants") or []
    if not variants:
        raise AssertionError("Response has no variants[]")
    return next((v for v in variants if v.get("is_recommended")), variants[0])
