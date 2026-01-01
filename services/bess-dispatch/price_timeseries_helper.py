"""
Price Timeseries Helper (v2.0.0).

Generates per-step price timeseries from ToU tariff configuration
and computes deterministic price_hash for debugging/reproducibility.

This module is the SINGLE SOURCE OF TRUTH for:
- Converting ToU zones to per-step price arrays
- Computing stable price_hash from price timeseries
- Validating price timeseries integrity
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from models import PriceTimeseriesPlnPerMwh, PriceConfig

logger = logging.getLogger(__name__)


def compute_price_hash(price_timeseries: PriceTimeseriesPlnPerMwh) -> str:
    """
    Compute SHA256 hash of price timeseries for deterministic identification.

    The hash is computed from a canonical JSON representation:
    - Keys sorted alphabetically
    - No whitespace
    - Arrays rounded to 6 decimal places for stability

    Args:
        price_timeseries: PriceTimeseriesPlnPerMwh model

    Returns:
        SHA256 hex digest (64 characters)
    """
    # Build canonical dict with rounded arrays
    canonical = {
        "export_price_pln_per_mwh": [round(p, 6) for p in price_timeseries.export_price_pln_per_mwh],
        "import_price_pln_per_mwh": [round(p, 6) for p in price_timeseries.import_price_pln_per_mwh],
        "other_fees_pln_per_mwh": [round(p, 6) for p in price_timeseries.other_fees_pln_per_mwh] if price_timeseries.other_fees_pln_per_mwh else [],
        "period_end": price_timeseries.period_end,
        "period_start": price_timeseries.period_start,
        "step_minutes": price_timeseries.step_minutes,
        "steps": price_timeseries.steps,
        "timezone": price_timeseries.timezone,
        "unserved_penalty_pln_per_kwh": [round(p, 6) for p in price_timeseries.unserved_penalty_pln_per_kwh] if price_timeseries.unserved_penalty_pln_per_kwh else [],
    }

    # Serialize to canonical JSON (sorted keys, no whitespace)
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))

    # Compute SHA256
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def generate_price_timeseries(
    prices: PriceConfig,
    n_steps: int,
    step_minutes: int,
    start_datetime: str,
    timezone: str = "Europe/Warsaw",
    unserved_penalty_pln_kwh: float = 10.0,
) -> PriceTimeseriesPlnPerMwh:
    """
    Generate per-step price timeseries from price configuration.

    For flat pricing (non-ToU), creates constant arrays.
    For ToU pricing, maps each timestep to the appropriate zone price.

    Args:
        prices: PriceConfig with import/export prices
        n_steps: Number of timesteps
        step_minutes: Time resolution (15 or 60)
        start_datetime: Period start (ISO 8601)
        timezone: Timezone for ToU zone mapping
        unserved_penalty_pln_kwh: Penalty rate for unserved load [PLN/kWh]

    Returns:
        PriceTimeseriesPlnPerMwh with per-step prices
    """
    # Extract base prices (already in PLN/MWh in PriceConfig)
    import_price_pln_mwh = prices.import_price_pln_mwh
    export_price_pln_mwh = prices.export_price_pln_mwh

    # For now, generate flat price arrays
    # TODO: In future PRs, integrate with ToU tariff system for zone-based pricing
    import_prices = [import_price_pln_mwh] * n_steps
    export_prices = [export_price_pln_mwh] * n_steps

    # Other fees - use other_fees_pln_mwh if available
    other_fees_pln_mwh = getattr(prices, 'other_fees_pln_mwh', 0.0)
    other_fees = [other_fees_pln_mwh] * n_steps

    # Unserved penalty (constant)
    unserved_penalty = [unserved_penalty_pln_kwh] * n_steps

    # Calculate period end
    try:
        start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
    except ValueError:
        # Fallback for simple date format
        start_dt = datetime.fromisoformat(start_datetime)

    end_dt = start_dt + timedelta(minutes=(n_steps - 1) * step_minutes)
    period_end = end_dt.isoformat()

    return PriceTimeseriesPlnPerMwh(
        import_price_pln_per_mwh=import_prices,
        export_price_pln_per_mwh=export_prices,
        other_fees_pln_per_mwh=other_fees,
        unserved_penalty_pln_per_kwh=unserved_penalty,
        step_minutes=step_minutes,
        steps=n_steps,
        timezone=timezone,
        period_start=start_datetime,
        period_end=period_end,
    )


def validate_price_timeseries(
    price_timeseries: PriceTimeseriesPlnPerMwh,
    expected_steps: int,
) -> Tuple[bool, List[str]]:
    """
    Validate price timeseries for correctness.

    Checks:
    - Array lengths match expected steps
    - No NaN or inf values
    - No negative prices (except export which is always >= 0)

    Args:
        price_timeseries: Price timeseries to validate
        expected_steps: Expected number of timesteps

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []

    # Check steps match
    if price_timeseries.steps != expected_steps:
        errors.append(f"steps mismatch: {price_timeseries.steps} != {expected_steps}")

    # Check array lengths
    if not price_timeseries.validate_lengths():
        errors.append("Array lengths do not match steps")

    # Check for invalid values
    if price_timeseries.has_invalid_values():
        errors.append("Contains NaN or inf values")

    # Check for negative import prices
    import math
    for i, p in enumerate(price_timeseries.import_price_pln_per_mwh):
        if p < 0:
            errors.append(f"Negative import price at step {i}: {p}")
            break  # Only report first occurrence

    # Export prices can be >= 0 (no negative check for export)

    return len(errors) == 0, errors
