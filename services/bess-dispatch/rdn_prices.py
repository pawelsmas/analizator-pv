"""
RDN Prices Fetcher
===================
Fetches RDN (Rynek Dnia Nastepnego / Day-Ahead Market) prices from the
Polish PSE (Polskie Sieci Elektroenergetyczne) API.

API endpoint: https://api.raporty.pse.pl/api/rce-pln

Prices are returned in PLN/kWh (converted from PLN/MWh).

Features:
- In-memory caching with TTL to avoid redundant API calls
- Fallback to synthetic average prices when API is unavailable
- Timezone handling (CET/CEST -> fixed CET offset for dispatch)
- Resampling from hourly to 15-min intervals

Version: 1.0.0
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PSE_API_URL = "https://api.raporty.pse.pl/api/rce-pln"
MWH_TO_KWH = 1000.0
CACHE_TTL_SECONDS = 3600  # 1 hour
REQUEST_TIMEOUT_SECONDS = 15

# CET fixed offset (+01:00) used by the dispatch engine
CET_FIXED = timezone(timedelta(hours=1))

# Synthetic fallback prices (PLN/MWh) by hour-of-day, based on typical
# Polish market averages.  These are rough 2024/2025 averages used only
# when the API is unreachable.
_FALLBACK_HOURLY_PLN_MWH: List[float] = [
    280, 260, 245, 240, 238, 250,   # 00-05  night valley
    290, 380, 420, 400, 370, 350,   # 06-11  morning ramp
    340, 330, 320, 330, 360, 410,   # 12-17  afternoon
    450, 430, 390, 360, 330, 300,   # 18-23  evening peak & decline
]

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: Dict[str, Tuple[float, Any]] = {}


def _cache_key(start_date: str, end_date: str) -> str:
    return f"rdn:{start_date}:{end_date}"


def _cache_get(key: str) -> Optional[Any]:
    """Return cached value if present and not expired, else None."""
    if key in _cache:
        ts, value = _cache[key]
        if time.time() - ts < CACHE_TTL_SECONDS:
            return value
        del _cache[key]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


def clear_cache() -> None:
    """Clear the entire RDN price cache."""
    _cache.clear()
    logger.info("RDN price cache cleared")


# ---------------------------------------------------------------------------
# Core API fetch
# ---------------------------------------------------------------------------

def fetch_rdn_prices(
    start_date: str,
    end_date: str,
    *,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch hourly RDN prices from the PSE API.

    Parameters
    ----------
    start_date : str
        Start date in ISO format ``YYYY-MM-DD``.
    end_date : str
        End date in ISO format ``YYYY-MM-DD`` (inclusive).
    use_cache : bool
        Whether to use the in-memory TTL cache (default ``True``).

    Returns
    -------
    list[dict]
        List of dicts with keys:
        - ``doba``       (str)  : trading day ``YYYY-MM-DD``
        - ``udtczas``    (str)  : timestamp ``YYYY-MM-DDTHH:MM:SS``
        - ``rce_pln``    (float): price in PLN/MWh
        - ``rce_pln_kwh``(float): price in PLN/kWh

    Raises
    ------
    RuntimeError
        If the API call fails and no cached/fallback data is available
        (only when ``use_cache=False`` *and* fallback is explicitly
        disabled in a future version).
    """
    key = _cache_key(start_date, end_date)
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            logger.debug("RDN cache hit for %s -> %s", start_date, end_date)
            return cached

    try:
        data = _fetch_from_api(start_date, end_date)
        logger.info(
            "Fetched %d RDN price records from PSE API (%s -> %s)",
            len(data), start_date, end_date,
        )
    except Exception as exc:
        logger.warning(
            "PSE API unavailable (%s); falling back to synthetic prices", exc,
        )
        data = _generate_fallback_prices(start_date, end_date)

    if use_cache:
        _cache_set(key, data)
    return data


def _fetch_from_api(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """
    Raw HTTP call to the PSE RCE-PLN endpoint.

    PSE API v2 (2024+) uses:
      - ``business_date`` instead of ``doba``
      - ``dtime`` instead of ``udtczas``
      - Returns 15-min intervals (96/day) — we aggregate to hourly.
      - Max ~100 records per request, so we iterate day-by-day.
    """
    dt_start = datetime.strptime(start_date, "%Y-%m-%d")
    dt_end = datetime.strptime(end_date, "%Y-%m-%d")

    all_records_15min: List[Dict[str, Any]] = []
    current = dt_start

    while current <= dt_end:
        day_str = current.strftime("%Y-%m-%d")
        params = {
            "$filter": f"business_date eq '{day_str}'",
        }
        try:
            resp = requests.get(
                PSE_API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()

            for row in payload.get("value", []):
                rce = float(row.get("rce_pln", 0.0))
                all_records_15min.append({
                    "doba": row.get("business_date", day_str),
                    "udtczas": row.get("dtime", ""),
                    "rce_pln": rce,
                    "rce_pln_kwh": rce / MWH_TO_KWH,
                })
        except Exception as exc:
            logger.warning("PSE API failed for %s: %s", day_str, exc)

        current += timedelta(days=1)

    if not all_records_15min:
        raise RuntimeError("No data fetched from PSE API")

    # Sort by timestamp
    all_records_15min.sort(key=lambda r: r["udtczas"])

    # Aggregate 15-min → hourly (average of 4 quarter-hours)
    hourly_records = _aggregate_15min_to_hourly(all_records_15min)
    logger.info(
        "PSE API: fetched %d 15-min records → %d hourly (%s to %s)",
        len(all_records_15min), len(hourly_records), start_date, end_date,
    )
    return hourly_records


def _aggregate_15min_to_hourly(
    records_15min: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate 15-min RDN records to hourly averages."""
    from collections import defaultdict

    # Group by (date, hour)
    buckets: Dict[str, List[float]] = defaultdict(list)
    bucket_doba: Dict[str, str] = {}

    for rec in records_15min:
        ts_str = rec["udtczas"]
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        # The 15-min period ending at HH:00 belongs to the previous hour
        # PSE convention: dtime is END of period, so 01:00 = period 00:45-01:00 = hour 00
        hour_key = ts.strftime("%Y-%m-%d") + f"T{ts.hour:02d}"
        # But for :15, :30, :45 the dtime shows next quarter
        # Actually PSE: dtime="2025-03-01 00:15:00" means period 00:00-00:15 → hour 00
        # dtime="2025-03-01 01:00:00" means period 00:45-01:00 → hour 00
        if ts.minute == 0 and ts.hour > 0:
            # This is the LAST quarter of the previous hour
            prev_hour = ts.hour - 1
            hour_key = ts.strftime("%Y-%m-%d") + f"T{prev_hour:02d}"
        else:
            hour_key = ts.strftime("%Y-%m-%d") + f"T{ts.hour:02d}"

        buckets[hour_key].append(rec["rce_pln"])
        bucket_doba[hour_key] = rec["doba"]

    hourly: List[Dict[str, Any]] = []
    for key in sorted(buckets.keys()):
        prices = buckets[key]
        avg_rce = sum(prices) / len(prices)
        date_part, hour_part = key.split("T")
        hourly.append({
            "doba": bucket_doba.get(key, date_part),
            "udtczas": f"{date_part}T{hour_part}:00:00",
            "rce_pln": round(avg_rce, 2),
            "rce_pln_kwh": round(avg_rce / MWH_TO_KWH, 6),
        })

    return hourly


# ---------------------------------------------------------------------------
# Fallback / synthetic prices
# ---------------------------------------------------------------------------

def _generate_fallback_prices(
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    """
    Generate synthetic hourly prices when the API is unavailable.

    Uses the ``_FALLBACK_HOURLY_PLN_MWH`` profile repeated for each day
    in the requested range.
    """
    dt_start = datetime.strptime(start_date, "%Y-%m-%d")
    dt_end = datetime.strptime(end_date, "%Y-%m-%d")

    records: List[Dict[str, Any]] = []
    current = dt_start
    while current <= dt_end:
        day_str = current.strftime("%Y-%m-%d")
        for hour in range(24):
            ts = current.replace(hour=hour, minute=0, second=0)
            rce = _FALLBACK_HOURLY_PLN_MWH[hour]
            records.append({
                "doba": day_str,
                "udtczas": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "rce_pln": rce,
                "rce_pln_kwh": rce / MWH_TO_KWH,
            })
        current += timedelta(days=1)
    return records


# ---------------------------------------------------------------------------
# Conversion to dispatch-ready numpy array
# ---------------------------------------------------------------------------

def rdn_to_price_array(
    rdn_data: List[Dict[str, Any]],
    time_index: np.ndarray,
    interval_minutes: int = 60,
) -> np.ndarray:
    """
    Convert a list of RDN records to a numpy price array aligned with
    the dispatch time index.

    Parameters
    ----------
    rdn_data : list[dict]
        Output of :func:`fetch_rdn_prices`.
    time_index : np.ndarray
        Array of ``datetime64`` or integer hour indices used by the
        dispatch engine.  Its length defines the output length.
    interval_minutes : int
        Dispatch interval in minutes (60 or 15).

    Returns
    -------
    np.ndarray
        Price array in **PLN/kWh**, same length as ``time_index``.

    Notes
    -----
    - For 60-min dispatch the mapping is 1:1.
    - For 15-min dispatch each hourly price is repeated 4 times.
    - If the RDN data is shorter than the time index the last known
      price is forward-filled; if empty the fallback profile is used.
    """
    n_steps = len(time_index)

    if not rdn_data:
        logger.warning("Empty RDN data; using fallback profile")
        hourly_kwh = np.array(_FALLBACK_HOURLY_PLN_MWH) / MWH_TO_KWH
        return _tile_hourly_to_steps(hourly_kwh, n_steps, interval_minutes)

    # Build hourly price vector from records (PLN/kWh)
    hourly_prices = np.array(
        [r["rce_pln_kwh"] for r in rdn_data], dtype=np.float64
    )

    if interval_minutes == 60:
        # Direct mapping - pad or truncate to match time_index length
        return _pad_or_truncate(hourly_prices, n_steps)

    if interval_minutes == 15:
        # Repeat each hourly value 4 times
        expanded = np.repeat(hourly_prices, 4)
        return _pad_or_truncate(expanded, n_steps)

    # Generic case: repeat proportionally
    repeats = 60 // interval_minutes
    expanded = np.repeat(hourly_prices, repeats)
    return _pad_or_truncate(expanded, n_steps)


def _tile_hourly_to_steps(
    hourly_24: np.ndarray,
    n_steps: int,
    interval_minutes: int,
) -> np.ndarray:
    """Tile a 24-element hourly profile to fill ``n_steps``."""
    repeats = 60 // interval_minutes
    one_day = np.repeat(hourly_24, repeats)  # 24*repeats elements
    n_days = (n_steps // len(one_day)) + 1
    tiled = np.tile(one_day, n_days)
    return tiled[:n_steps]


def _pad_or_truncate(arr: np.ndarray, n: int) -> np.ndarray:
    """Pad (forward-fill last value) or truncate ``arr`` to length ``n``."""
    if len(arr) >= n:
        return arr[:n]
    pad_value = arr[-1] if len(arr) > 0 else 0.0
    return np.concatenate([arr, np.full(n - len(arr), pad_value)])


# ---------------------------------------------------------------------------
# Annual statistics helper
# ---------------------------------------------------------------------------

def get_annual_rdn_stats(year: int) -> Dict[str, float]:
    """
    Fetch RDN prices for a full calendar year and compute summary
    statistics.

    Parameters
    ----------
    year : int
        Calendar year (e.g. 2025).

    Returns
    -------
    dict
        Keys (all values in **PLN/MWh**):
        - ``year``
        - ``mean``
        - ``median``
        - ``min``
        - ``max``
        - ``std``
        - ``p10``  (10th percentile)
        - ``p25``  (25th percentile)
        - ``p75``  (75th percentile)
        - ``p90``  (90th percentile)
        - ``count`` (number of hourly records)
    """
    start = f"{year}-01-01"
    end = f"{year}-12-31"

    data = fetch_rdn_prices(start, end)

    if not data:
        logger.warning("No RDN data for year %d", year)
        return {"year": year, "count": 0}

    prices_mwh = np.array([r["rce_pln"] for r in data], dtype=np.float64)

    return {
        "year": year,
        "count": int(len(prices_mwh)),
        "mean": float(np.mean(prices_mwh)),
        "median": float(np.median(prices_mwh)),
        "min": float(np.min(prices_mwh)),
        "max": float(np.max(prices_mwh)),
        "std": float(np.std(prices_mwh)),
        "p10": float(np.percentile(prices_mwh, 10)),
        "p25": float(np.percentile(prices_mwh, 25)),
        "p75": float(np.percentile(prices_mwh, 75)),
        "p90": float(np.percentile(prices_mwh, 90)),
    }


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def fetch_rdn_for_dispatch(
    start_date: str,
    end_date: str,
    n_steps: int,
    interval_minutes: int = 60,
) -> np.ndarray:
    """
    One-call convenience: fetch RDN prices and return a dispatch-ready
    numpy array in PLN/kWh.

    Parameters
    ----------
    start_date, end_date : str
        Date range in ``YYYY-MM-DD`` format.
    n_steps : int
        Number of time steps expected by the dispatch engine.
    interval_minutes : int
        Dispatch interval (60 or 15).

    Returns
    -------
    np.ndarray
        Price array of length ``n_steps`` in PLN/kWh.
    """
    data = fetch_rdn_prices(start_date, end_date)
    dummy_index = np.arange(n_steps)
    return rdn_to_price_array(data, dummy_index, interval_minutes)
