"""
Tariff Presets Helper (v2.1.0).

Manages tariff presets registry and generates pricing from presets.

This module is the SINGLE SOURCE OF TRUTH for:
- Loading tariff presets from registry
- Generating price timeseries from a preset
- Validating preset configurations
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any

from models import PriceConfig, PriceTimeseriesPlnPerMwh

logger = logging.getLogger(__name__)

# Path to presets registry
# In container: /app/docs/tariffs/presets.json (mounted volume)
# In development: ../../docs/tariffs/presets.json (relative to service dir)
_CONTAINER_PATH = os.path.join(os.path.dirname(__file__), "docs", "tariffs", "presets.json")
_DEV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "tariffs", "presets.json")
PRESETS_FILE = _CONTAINER_PATH if os.path.exists(_CONTAINER_PATH) else _DEV_PATH

# Cached presets
_cached_presets: Optional[Dict[str, Any]] = None


def load_presets() -> Dict[str, Any]:
    """
    Load tariff presets from registry file.

    Returns:
        Dict with 'presets' list
    """
    global _cached_presets

    if _cached_presets is not None:
        return _cached_presets

    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            _cached_presets = json.load(f)
        logger.info(f"Loaded {len(_cached_presets.get('presets', []))} tariff presets")
        return _cached_presets
    except FileNotFoundError:
        logger.warning(f"Presets file not found: {PRESETS_FILE}")
        return {"presets": []}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in presets file: {e}")
        return {"presets": []}


def list_presets() -> List[Dict[str, str]]:
    """
    List available tariff presets (id and label only).

    Returns:
        List of dicts with 'id' and 'label' keys
    """
    data = load_presets()
    return [
        {"id": p["id"], "label": p["label"]}
        for p in data.get("presets", [])
    ]


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a tariff preset by ID.

    Args:
        preset_id: Preset identifier (e.g., 'pl_flat_2026')

    Returns:
        Preset dict or None if not found
    """
    data = load_presets()
    for preset in data.get("presets", []):
        if preset["id"] == preset_id:
            return preset
    return None


def preset_to_price_config(preset: Dict[str, Any]) -> PriceConfig:
    """
    Convert a preset to PriceConfig.

    For flat presets, uses the import_price_pln_per_mwh directly.
    For ToU presets, uses an average or peak price as default.

    Args:
        preset: Preset dict from registry

    Returns:
        PriceConfig object
    """
    import_price = preset.get("import_price_pln_per_mwh")

    # For ToU presets, import_price is null - use peak as default
    if import_price is None:
        import_price = preset.get("weekday_peak_price_pln_per_mwh", 500.0)

    export_price = preset.get("export_price_pln_per_mwh", 0.0)
    other_fees = preset.get("other_fees_pln_per_mwh", 0.0)

    return PriceConfig(
        import_price_pln_mwh=import_price,
        export_price_pln_mwh=export_price,
        other_fees_pln_mwh=other_fees,
    )


def is_flat_preset(preset: Dict[str, Any]) -> bool:
    """
    Check if a preset is a flat (non-ToU) tariff.

    Args:
        preset: Preset dict

    Returns:
        True if flat, False if ToU
    """
    # ToU presets have weekday_peak_hours or similar fields
    return "weekday_peak_hours" not in preset


def generate_price_timeseries_from_preset(
    preset_id: str,
    n_steps: int,
    step_minutes: int,
    start_datetime: str,
    timezone: str = "Europe/Warsaw",
) -> Optional[PriceTimeseriesPlnPerMwh]:
    """
    Generate price timeseries from a preset.

    Args:
        preset_id: Preset identifier
        n_steps: Number of timesteps
        step_minutes: Time resolution (15 or 60)
        start_datetime: Period start (ISO 8601)
        timezone: Timezone for ToU zone mapping

    Returns:
        PriceTimeseriesPlnPerMwh or None if preset not found
    """
    from datetime import datetime, timedelta
    from price_timeseries_helper import generate_price_timeseries

    preset = get_preset(preset_id)
    if not preset:
        return None

    if is_flat_preset(preset):
        # Flat preset - use simple generation
        price_config = preset_to_price_config(preset)
        return generate_price_timeseries(
            prices=price_config,
            n_steps=n_steps,
            step_minutes=step_minutes,
            start_datetime=start_datetime,
            timezone=timezone,
        )
    else:
        # ToU preset - generate with time-varying prices
        # Parse start datetime
        try:
            start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
        except ValueError:
            start_dt = datetime.fromisoformat(start_datetime)

        import_prices = []
        export_prices = []
        other_fees = []

        peak_hours = set(preset.get("weekday_peak_hours", []))
        peak_price = preset.get("weekday_peak_price_pln_per_mwh", 700.0)
        offpeak_price = preset.get("weekday_offpeak_price_pln_per_mwh", 350.0)
        weekend_price = preset.get("weekend_price_pln_per_mwh", 350.0)
        export_price = preset.get("export_price_pln_per_mwh", 0.0)
        fees = preset.get("other_fees_pln_per_mwh", 0.0)

        for i in range(n_steps):
            step_dt = start_dt + timedelta(minutes=i * step_minutes)
            hour = step_dt.hour
            weekday = step_dt.weekday()  # 0=Monday, 6=Sunday

            if weekday >= 5:  # Weekend
                import_prices.append(weekend_price)
            elif hour in peak_hours:
                import_prices.append(peak_price)
            else:
                import_prices.append(offpeak_price)

            export_prices.append(export_price)
            other_fees.append(fees)

        # Calculate period end
        end_dt = start_dt + timedelta(minutes=(n_steps - 1) * step_minutes)

        return PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=import_prices,
            export_price_pln_per_mwh=export_prices,
            other_fees_pln_per_mwh=other_fees,
            unserved_penalty_pln_per_kwh=[10.0] * n_steps,
            step_minutes=step_minutes,
            steps=n_steps,
            timezone=timezone,
            period_start=start_datetime,
            period_end=end_dt.isoformat(),
        )


def reload_presets() -> None:
    """Force reload of presets from file."""
    global _cached_presets
    _cached_presets = None
    load_presets()
