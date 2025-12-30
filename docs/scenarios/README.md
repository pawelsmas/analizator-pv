# BESS Sizing Scenarios for Correctness Validation

This directory contains scenario definitions for validating BESS sizing calculations.

## Scenario Format

Each scenario is a JSON file with the following structure:

```json
{
  "scenario_id": "baseline_stacked_no_arb",
  "description": "Baseline scenario: STACKED mode without arbitrage",
  "request_file": "scripts/smoke/sizing_stacked_no_arbitrage.json",
  "expected_kpis": {
    "recommended_variant": "small",
    "npv_pln": -68114.09,
    "payback_years": 3949.56,
    "net_savings_pln": 15.31
  },
  "tolerances": {
    "default_abs": 1.0,
    "default_rel": 0.001
  }
}
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| scenario_id | string | Unique identifier for the scenario |
| description | string | Human-readable description |
| request_file | string | Path to sizing request JSON file (relative to repo root) |
| expected_kpis | object | Expected KPI values (numeric fields only, no strings) |
| tolerances | object | Tolerance configuration (optional) |

## Running Validation

```bash
# Run all scenarios
python scripts/validate_scenarios.py

# Run specific scenario
python scripts/validate_scenarios.py baseline_stacked_no_arb

# Run with Makefile
make validate
```

## Adding New Scenarios

1. Create a sizing request JSON file in `scripts/smoke/` or similar location
2. Run the sizing to get actual KPI values
3. Create a scenario JSON file in `docs/scenarios/`
4. Run validation to verify the scenario passes
