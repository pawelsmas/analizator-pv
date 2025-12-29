"""
Cache Helper for BESS Dispatch (v0.9.0)
=======================================

Provides:
- Deterministic request hash computation (SHA-256)
- In-memory LRU cache for sizing results
- Cache metadata (CacheInfo) generation

The cache is optional and can be disabled per-request.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from models import CacheInfo, CacheStatus


# Default cache TTL (1 hour)
DEFAULT_CACHE_TTL_SECONDS = 3600

# In-memory cache storage: request_hash -> (result_dict, run_id, cached_at)
_cache_store: Dict[str, Tuple[Dict[str, Any], str, str]] = {}

# Maximum cache entries
MAX_CACHE_ENTRIES = 1000


def compute_request_hash(request_dict: Dict[str, Any]) -> str:
    """
    Compute deterministic SHA-256 hash of request.

    The hash is computed from a canonical JSON representation:
    - Keys are sorted alphabetically
    - No whitespace
    - Consistent float formatting

    Parameters:
    -----------
    request_dict : Dict[str, Any]
        Request payload as dictionary

    Returns:
    --------
    str : SHA-256 hash hex digest (64 characters)

    Example:
    --------
    >>> req = {"load_kw": [100, 120], "pv_generation_kw": [50, 70]}
    >>> h1 = compute_request_hash(req)
    >>> h2 = compute_request_hash(req)
    >>> assert h1 == h2  # Same input = same hash
    """
    # Create canonical JSON string
    # sort_keys=True ensures deterministic key ordering
    # separators removes whitespace for compact representation
    canonical = json.dumps(
        request_dict,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        default=_json_serializer,
    )

    # Compute SHA-256 hash
    hash_obj = hashlib.sha256(canonical.encode('utf-8'))
    return hash_obj.hexdigest()


def _json_serializer(obj: Any) -> Any:
    """JSON serializer for types not supported by default json module."""
    if hasattr(obj, 'value'):  # Enum
        return obj.value
    if hasattr(obj, 'isoformat'):  # datetime
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def generate_run_id() -> str:
    """
    Generate unique run ID for a new computation.

    Returns:
    --------
    str : UUID v4 string
    """
    return str(uuid.uuid4())


def get_cache_entry(request_hash: str) -> Optional[Tuple[Dict[str, Any], str, str]]:
    """
    Look up cache entry by request hash.

    Parameters:
    -----------
    request_hash : str
        SHA-256 hash of request

    Returns:
    --------
    Optional[Tuple[Dict, str, str]] : (result_dict, run_id, cached_at) or None if miss
    """
    return _cache_store.get(request_hash)


def set_cache_entry(
    request_hash: str,
    result_dict: Dict[str, Any],
    run_id: str,
) -> str:
    """
    Store result in cache.

    Parameters:
    -----------
    request_hash : str
        SHA-256 hash of request
    result_dict : Dict[str, Any]
        Sizing result as dictionary
    run_id : str
        Run ID for this computation

    Returns:
    --------
    str : ISO 8601 timestamp when cached
    """
    # Evict oldest entries if cache is full
    if len(_cache_store) >= MAX_CACHE_ENTRIES:
        # Simple eviction: remove first entry (oldest)
        oldest_key = next(iter(_cache_store))
        del _cache_store[oldest_key]

    cached_at = datetime.now(timezone.utc).isoformat()
    _cache_store[request_hash] = (result_dict, run_id, cached_at)
    return cached_at


def clear_cache() -> int:
    """
    Clear all cache entries.

    Returns:
    --------
    int : Number of entries cleared
    """
    count = len(_cache_store)
    _cache_store.clear()
    return count


def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics.

    Returns:
    --------
    Dict with: entries, max_entries, hit_rate (placeholder)
    """
    return {
        "entries": len(_cache_store),
        "max_entries": MAX_CACHE_ENTRIES,
    }


def build_cache_info(
    request_hash: str,
    run_id: str,
    cache_status: CacheStatus,
    cached_at: Optional[str] = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> CacheInfo:
    """
    Build CacheInfo object for response.

    Parameters:
    -----------
    request_hash : str
        SHA-256 hash of request
    run_id : str
        Unique run identifier
    cache_status : CacheStatus
        HIT, MISS, or DISABLED
    cached_at : Optional[str]
        ISO 8601 timestamp when cached (for HIT)
    ttl_seconds : int
        Cache time-to-live

    Returns:
    --------
    CacheInfo : Cache metadata object
    """
    return CacheInfo(
        request_hash=request_hash,
        run_id=run_id,
        cache_status=cache_status,
        cached_at=cached_at,
        ttl_seconds=ttl_seconds if cache_status != CacheStatus.DISABLED else None,
    )
