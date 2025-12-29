#!/usr/bin/env python3
"""
Generate golden master file for v0.5.0 finance regression tests.

This script calls the sizing API with finance_config to capture:
- finance_assumptions at top level
- finance_summary per variant with:
  - cashflow_timeseries
  - discount_rate_sensitivity

Usage:
    python tests/regression/generate_finance_golden.py
"""
import json
import requests
from pathlib import Path

BESS_DISPATCH_URL = "http://localhost:8031"
GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_sample_load_pv(hours: int = 168):
    """Generate sample load and PV profiles (1 week)."""
    # Simple pattern: higher load during day, PV peaks at noon
    load_kw = []
    pv_kw = []

    for h in range(hours):
        hour_of_day = h % 24

        # Load: base 400kW, peak 800kW during business hours
        if 8 <= hour_of_day <= 18:
            load = 600.0 + 200.0 * (1 - abs(hour_of_day - 13) / 5)
        else:
            load = 400.0

        # PV: peaks at noon, zero at night
        if 6 <= hour_of_day <= 20:
            pv = 250.0 * max(0, 1 - abs(hour_of_day - 13) / 7)
        else:
            pv = 0.0

        load_kw.append(load)
        pv_kw.append(pv)

    return load_kw, pv_kw


def main():
    print("Generating v0.5.0 finance golden master...")

    # Generate 1 week of data
    load_kw, pv_kw = generate_sample_load_pv(168)

    # Request with finance_config for cashflow + sensitivity
    request = {
        "load_kw": load_kw,
        "pv_generation_kw": pv_kw,
        "mode": "stacked",
        "peak_limit_kw": 600.0,  # Required for STACKED mode
        "import_price_pln_mwh": 1251.0,
        "export_price_pln_mwh": 400.0,  # Include export for broader test coverage
        "start_date": "2025-01-01",
        "finance_config": {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "discount_rate_sweep": [0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
        },
    }

    # Make API call
    print(f"Calling {BESS_DISPATCH_URL}/sizing...")
    response = requests.post(
        f"{BESS_DISPATCH_URL}/sizing",
        json=request,
        timeout=120,
    )

    if response.status_code != 200:
        print(f"ERROR: API returned {response.status_code}")
        print(response.text)
        return

    result = response.json()

    # Verify we got finance data
    if "finance_assumptions" not in result:
        print("ERROR: Response missing finance_assumptions")
        return

    variants = result.get("variants", [])
    if not variants:
        print("ERROR: No variants in response")
        return

    first_variant = variants[0]
    fs = first_variant.get("finance_summary", {})

    if "cashflow_timeseries" not in fs:
        print("ERROR: finance_summary missing cashflow_timeseries")
        return

    if "discount_rate_sensitivity" not in fs:
        print("ERROR: finance_summary missing discount_rate_sensitivity")
        return

    # Save golden file
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden_path = GOLDEN_DIR / "scenario_finance_v050.json"
    request_path = GOLDEN_DIR / "scenario_finance_v050_request.json"

    with open(golden_path, "w") as f:
        json.dump(result, f, indent=2)

    with open(request_path, "w") as f:
        json.dump(request, f, indent=2)

    print(f"Saved golden master to: {golden_path}")
    print(f"Saved request to: {request_path}")

    # Summary
    print("\nGolden file contents:")
    print(f"  - finance_assumptions: {list(result.get('finance_assumptions', {}).keys())}")
    print(f"  - variants: {len(variants)}")
    print(f"  - cashflow_timeseries length: {len(fs.get('cashflow_timeseries', []))}")
    print(f"  - discount_rate_sensitivity length: {len(fs.get('discount_rate_sensitivity', []))}")
    print(f"  - NPV from finance_summary: {fs.get('npv_pln', 'N/A'):.2f}")


if __name__ == "__main__":
    main()
