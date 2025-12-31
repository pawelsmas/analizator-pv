#!/usr/bin/env python3
"""
Capture scenario from existing run_id.

Creates a scenario folder in docs/scenarios/<name>/ with:
- request.json: Original sizing request
- expected_kpis.json: KPIs extracted from actual response
- tolerances.json: Default tolerances

Usage:
    python scripts/capture_scenario.py --run-id <UUID> --name <scenario_name>
    python scripts/capture_scenario.py --run-id <UUID> --name <scenario_name> --base-url http://localhost:8031
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests


# -----------------------------------------------------------------------------
# Default tolerances
# -----------------------------------------------------------------------------

DEFAULT_TOLERANCES = {
    "default_abs": 1.0,
    "default_rel": 0.01,
    "per_field_abs": {
        "payback_years": 0.05,
        "irr_pct": 0.5,
        "battery_throughput_mwh": 0.001,
    },
}


# -----------------------------------------------------------------------------
# KPI Extraction (same logic as validation_kpis.py)
# -----------------------------------------------------------------------------

def extract_kpis_from_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract KPI values from sizing response.

    Uses the recommended variant's finance_summary, savings_breakdown,
    and dispatch_summary.energy_flows.totals_mwh.
    """
    kpis: Dict[str, Any] = {}

    # Get recommended variant name
    recommended_variant = resp.get("recommended_variant", "unknown")
    kpis["recommended_variant"] = recommended_variant

    objective_used = resp.get("objective_used")
    if objective_used:
        kpis["objective_used"] = objective_used

    # Find the recommended variant in variants array
    variants = resp.get("variants", [])
    variant_data = None
    for v in variants:
        if v.get("variant") == recommended_variant:
            variant_data = v
            break

    if variant_data is None and variants:
        variant_data = variants[0]

    if variant_data is None:
        return kpis

    # Extract finance_summary
    finance = variant_data.get("finance_summary", {})
    kpis["npv_pln"] = finance.get("npv_pln", variant_data.get("npv_pln", 0.0))
    kpis["payback_years"] = finance.get("payback_years", variant_data.get("simple_payback_years", 0.0))
    irr_pct = finance.get("irr_pct")
    if irr_pct is not None:
        kpis["irr_pct"] = irr_pct

    # Extract savings_breakdown
    savings = variant_data.get("savings_breakdown", {})
    kpis["net_savings_pln"] = savings.get("net_savings_pln", 0.0)
    kpis["energy_savings_pln"] = savings.get("energy_savings_pln", 0.0)
    kpis["capacity_fee_savings_pln"] = savings.get("capacity_fee_savings_pln", 0.0)
    kpis["demand_charge_savings_pln"] = savings.get("demand_charge_savings_pln", 0.0)
    kpis["arbitrage_savings_pln"] = savings.get("arbitrage_savings_pln", 0.0)
    kpis["export_revenue_savings_pln"] = savings.get("export_revenue_savings_pln", 0.0)
    kpis["degradation_cost_pln"] = savings.get("degradation_cost_pln", 0.0)
    kpis["battery_throughput_mwh"] = savings.get("battery_throughput_mwh", 0.0)

    # Extract energy flows from dispatch_summary
    dispatch = variant_data.get("dispatch_summary", {})
    energy_flows = dispatch.get("energy_flows", {})
    totals = energy_flows.get("totals_mwh", {})

    kpis["grid_import_mwh"] = totals.get("grid_import_mwh", 0.0)
    kpis["grid_export_mwh"] = totals.get("grid_export_mwh", 0.0)
    kpis["pv_curtail_mwh"] = totals.get("pv_curtail_mwh", 0.0)

    # Unserved load from constraint_summary
    constraint_summary = dispatch.get("constraint_summary") or {}
    kpis["unserved_load_kwh"] = constraint_summary.get("unserved_load_kwh", 0.0)

    return kpis


# -----------------------------------------------------------------------------
# Scenario Writer
# -----------------------------------------------------------------------------

def write_scenario_folder(
    output_dir: Path,
    name: str,
    request: Dict[str, Any],
    expected_kpis: Dict[str, Any],
    tolerances: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
) -> Path:
    """
    Write scenario files to a folder.

    Creates:
        <output_dir>/<name>/request.json
        <output_dir>/<name>/expected_kpis.json
        <output_dir>/<name>/tolerances.json
        <output_dir>/<name>/scenario.json (combined format for compatibility)

    Args:
        output_dir: Base directory for scenarios (e.g., docs/scenarios)
        name: Scenario name (will be folder name)
        request: Sizing request dict
        expected_kpis: Expected KPI values dict
        tolerances: Tolerance configuration (uses defaults if None)
        description: Optional scenario description

    Returns:
        Path to created scenario folder
    """
    if tolerances is None:
        tolerances = DEFAULT_TOLERANCES.copy()

    scenario_dir = output_dir / name
    scenario_dir.mkdir(parents=True, exist_ok=True)

    # Write request.json
    request_path = scenario_dir / "request.json"
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request, f, indent=2, ensure_ascii=False)

    # Write expected_kpis.json
    kpis_path = scenario_dir / "expected_kpis.json"
    with open(kpis_path, "w", encoding="utf-8") as f:
        json.dump(expected_kpis, f, indent=2, ensure_ascii=False)

    # Write tolerances.json
    tolerances_path = scenario_dir / "tolerances.json"
    with open(tolerances_path, "w", encoding="utf-8") as f:
        json.dump(tolerances, f, indent=2, ensure_ascii=False)

    # Write combined scenario.json for compatibility with existing runner
    combined = {
        "scenario_id": name,
        "description": description or f"Captured scenario: {name}",
        "request_file": f"docs/scenarios/{name}/request.json",
        "expected_kpis": {k: v for k, v in expected_kpis.items() if isinstance(v, (int, float))},
        "tolerances": tolerances,
    }
    scenario_path = scenario_dir / "scenario.json"
    with open(scenario_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    return scenario_dir


# -----------------------------------------------------------------------------
# Run Fetcher
# -----------------------------------------------------------------------------

def fetch_run(base_url: str, run_id: str) -> Dict[str, Any]:
    """
    Fetch run data from /runs/{run_id} endpoint.

    Returns dict with 'request' and 'response' keys.
    """
    url = f"{base_url}/runs/{run_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Capture scenario from existing run_id",
        epilog="Example: python scripts/capture_scenario.py --run-id abc123 --name my_scenario",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Run ID to capture",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Scenario name (will be folder name in docs/scenarios/)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8031",
        help="Base URL of bess-dispatch API (default: http://localhost:8031)",
    )
    parser.add_argument(
        "--out",
        default="docs/scenarios",
        help="Output directory (default: docs/scenarios)",
    )
    parser.add_argument(
        "--description",
        help="Optional scenario description",
    )

    args = parser.parse_args()

    # Fetch run data
    print(f"Fetching run {args.run_id} from {args.base_url}...")
    try:
        run_data = fetch_run(args.base_url, args.run_id)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Error: Run {args.run_id} not found", file=sys.stderr)
            sys.exit(1)
        raise

    # Extract request and response
    request = run_data.get("request")
    response = run_data.get("response")

    if not request:
        print("Error: Run has no request data", file=sys.stderr)
        sys.exit(1)

    if not response:
        print("Error: Run has no response data", file=sys.stderr)
        sys.exit(1)

    # Extract KPIs from response
    expected_kpis = extract_kpis_from_response(response)
    print(f"Extracted {len(expected_kpis)} KPIs from response")

    # Write scenario folder
    output_dir = Path(args.out)
    scenario_dir = write_scenario_folder(
        output_dir=output_dir,
        name=args.name,
        request=request,
        expected_kpis=expected_kpis,
        tolerances=DEFAULT_TOLERANCES.copy(),
        description=args.description,
    )

    print(f"Scenario saved to: {scenario_dir}")
    print(f"  - request.json")
    print(f"  - expected_kpis.json")
    print(f"  - tolerances.json")
    print(f"  - scenario.json (combined format)")


if __name__ == "__main__":
    main()
