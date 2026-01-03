# Decision Drivers v4.5.0

## Overview

Decision Drivers enable intelligent BESS sizing recommendations beyond just NPV.
This solves the "always recommend 1h" problem by introducing:

- **Multiple objectives**: NPV, IRR, LCOS, Payback, Self-consumption, Peak reduction, Resilience
- **Recommendation policy**: Near-optimal tolerance with tie-breakers
- **Profiles**: Pre-configured objective + policy combinations

## Objectives

| Objective | Direction | Description |
|-----------|-----------|-------------|
| `npv` | Maximize | Net Present Value (default) |
| `irr` | Maximize | Internal Rate of Return |
| `payback` | Minimize | Simple Payback Period |
| `self_consumption` | Maximize | PV self-consumption rate |
| `peak_reduction` | Maximize | Peak demand reduction |
| `lcos` | Minimize | Levelized Cost of Storage |
| `resilience` | Maximize | Backup capability |

### Aliases
- `lcoe` → `lcos` (LCOE is technically incorrect for storage)
- `self_consumption_rate` → `self_consumption`

## LCOS Formula

```
LCOS = (CAPEX + Σ(OPEX_t / (1+r)^t)) / Σ(Throughput_t / (1+r)^t)
```

LCOS represents the average cost per MWh of energy stored and discharged
over the battery's lifetime, accounting for the time value of money.

**Typical values**: 200-500 PLN/MWh for behind-the-meter BESS.

## Profiles

| Profile | Objective | Description |
|---------|-----------|-------------|
| `balanced` | NPV | NPV with self-consumption/duration tie-breakers |
| `pv_self_consumption` | Self-consumption | Maximize PV usage, require positive NPV |
| `commercial_peak_shaving` | Peak reduction | Demand charge optimization |
| `arbitrage` | NPV | NPV for grid arbitrage scenarios |
| `resilience_backup` | Resilience | Maximize backup, prefer longer duration |

## Recommendation Policy

```json
{
  "near_optimal_tolerance_pct": 5.0,
  "tie_breakers": ["self_consumption_rate", "duration_h"],
  "min_npv_pln": 0
}
```

### How it works

1. Score all variants by primary objective
2. Find variants within `tolerance_pct` of best
3. Apply tie-breakers in order until winner found
4. Return winner with `is_near_optimal=true` if tie-breaker was used

### Example

NPV scores: 1h=100k, 2h=98k, 4h=85k

With 5% tolerance: 1h and 2h are near-optimal (98k is within 5% of 100k)

Tie-breaker on `self_consumption_rate`: 2h wins (0.85 vs 0.70)

Result: 2h variant recommended with `reason_code: npv_near_optimal_tie_break`

## API Usage

```json
{
  "optimization": { "objective": "npv" },
  "recommendation_policy": {
    "near_optimal_tolerance_pct": 5.0,
    "tie_breakers": ["self_consumption_rate", "duration_h"]
  }
}
```

Or use a profile:

```json
{
  "profile": "balanced"
}
```

## Response

```json
{
  "recommendations": [
    {
      "objective": "npv",
      "variant": "medium_2h",
      "reason_code": "npv_near_optimal_tie_break",
      "is_near_optimal": true,
      "tie_breaker_used": "self_consumption_rate"
    }
  ],
  "duration_sweep": [
    {"duration_h": 1, "npv_pln": 100000},
    {"duration_h": 2, "npv_pln": 98000},
    {"duration_h": 4, "npv_pln": 85000}
  ]
}
```
