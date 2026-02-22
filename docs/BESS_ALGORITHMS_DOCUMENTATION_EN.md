# BESS Algorithms Documentation - ANALIZATOR PV

**Version:** 2.0
**Last Updated:** January 2026
**Author:** Energy Studio Team

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Peak Shaving Algorithms](#2-peak-shaving-algorithms)
3. [Dispatch Strategies (Control Algorithms)](#3-dispatch-strategies-control-algorithms)
4. [BESS Sizing Algorithms](#4-bess-sizing-algorithms)
5. [Economic Calculations](#5-economic-calculations)
6. [Degradation Models](#6-degradation-models)
7. [Tariff Optimization](#7-tariff-optimization)
8. [Capacity Fee (Polish Market)](#8-capacity-fee-polish-market)
9. [Monte Carlo Simulation](#9-monte-carlo-simulation)
10. [Grid Constraints](#10-grid-constraints)
11. [Revenue Stacking](#11-revenue-stacking)
12. [Technology Stack](#12-technology-stack)

---

## 1. Introduction

The Energy Studio system implements a comprehensive set of algorithms for analysis, sizing, and optimization of Battery Energy Storage Systems (BESS). This documentation describes all key algorithms used in the system.

### 1.1 BESS Functionality Scope

- **Peak Shaving** - reduction of power demand peaks
- **PV Shifting** - time-shifting of PV surplus
- **ToU Arbitrage** - exploiting energy price differences
- **Capacity Fee** - reduction of capacity market charges
- **Risk Analysis** - Monte Carlo simulations

---

## 2. Peak Shaving Algorithms

### 2.1 Percentile Threshold Analysis

**Location:** `services/frontend-economics/consumption.js` (lines ~700-2308)

**Purpose:** Identify optimal peak cut-off threshold for BESS

#### Methodology

1. **Sort data** - hourly power values from highest to lowest
2. **Calculate percentile thresholds** - P100, P99.5, P99, P98, P97, P95
3. **Count exceedances** - number of hours above each threshold
4. **Group events** - combine consecutive hours into time blocks
5. **Calculate energy to shave** - (power - threshold) × time [kWh]

#### Formulas

```
Threshold Pxx = power value where xx% of hours are above

Excess energy = Σ max(0, P[t] - threshold) × Δt

Peak reduction [%] = (P_max - threshold) / P_max × 100
```

#### Profitability Rating

| Exceedance Hours | Rating |
|------------------|--------|
| ≤50 hours | Very Profitable |
| ≤100 hours | Profitable |
| ≤500 hours | Possible |
| >500 hours | Not Profitable |

#### Example

```
Input data: 8760 hourly values [kW]
Annual peak: 1245 kW

Results:
P99.5 (threshold 968 kW):
- 42 exceedance hours annually
- 3,310 kWh to shave
- Peak reduction: 22.3%
- Rating: Very Profitable
```

### 2.2 Block Grouping Algorithm

**Location:** `services/frontend-economics/consumption.js` (line ~1130)

**Function:** `groupConsecutiveEvents()`

**Purpose:** Group individual exceedance hours into continuous time blocks

#### Logic

```
1. Sort events chronologically
2. Start first block
3. For each event:
   - If gap ≤ tolerance (1.5 × interval): extend block
   - If gap > tolerance: finalize block, start new one
```

#### Block Structure

```javascript
{
  startTime: Date,        // block start
  endTime: Date,          // block end
  durationHours: number,  // duration [h]
  maxPowerKW: number,     // maximum power in block [kW]
  totalExcessKWh: number, // total excess energy [kWh]
  intervalCount: number   // number of intervals
}
```

---

## 3. Dispatch Strategies (Control Algorithms)

### 3.1 PV-Surplus Dispatch (Self-Consumption)

**Location:** `services/bess-dispatch/dispatch_engine.py`

**Purpose:** Maximize self-consumption of PV energy

#### Algorithm

```
FOR each timestep t:
  1. Direct consumption = min(PV[t], Load[t])
  2. Surplus = PV[t] - direct consumption
  3. Deficit = Load[t] - direct consumption

  4. IF Surplus > 0:
     - Charge battery: min(surplus, P_max) considering SOC
     - Excess → curtailment (0-export model)

  5. IF Deficit > 0:
     - Discharge battery: min(deficit, P_max) to SOC_min
     - Remainder → grid import
```

#### Key Parameters

| Parameter | Description | Typical Value |
|-----------|-------------|---------------|
| P_max | Rated power [kW] | project-dependent |
| E_nom | Capacity [kWh] | project-dependent |
| η_roundtrip | Round-trip efficiency | 90% |
| η_one_way | One-way efficiency | √0.90 ≈ 94.87% |
| SOC_min | Minimum SOC | 10% |
| SOC_max | Maximum SOC | 90% |

### 3.2 Peak Shaving Dispatch

**Location:** `services/bess-dispatch/dispatch_engine.py`

**Purpose:** Reduce grid import peaks (lower demand charges)

#### Algorithm

```
PARAMETER: peak_limit_kw [cut-off threshold]

FOR each timestep t:
  net_load[t] = Load[t] - PV[t]

  IF net_load[t] > peak_limit_kw:
    required_discharge = net_load[t] - peak_limit_kw
    discharge[t] = min(required, P_max, available_SOC)
    grid_import[t] = net_load[t] - discharge[t]
    new_peak = max(new_peak, grid_import[t])

  ELSE IF 0 < net_load[t] ≤ peak_limit_kw:
    headroom = peak_limit_kw - net_load[t]
    IF SOC < SOC_max:
      charge[t] = min(headroom, P_max, available_space)

  ELSE (net_load[t] ≤ 0):
    surplus = -net_load[t]
    curtailment[t] = surplus  (0-export)
```

#### Metrics

```
Original peak = max(net_load > 0)
New peak = max(grid_import after BESS)
Peak reduction [%] = (original - new) / original × 100
```

### 3.3 STACKED Dispatch (Hybrid Mode)

**Location:** `services/bess-dispatch/dispatch_engine.py`

**Purpose:** Single battery performs both PV shifting and peak shaving with SOC reserve

#### Priority-Based Algorithm

```
reserve_soc = E_nom × reserve_fraction  [e.g., 30%]
pv_soc_min = max(SOC_min × E_nom, reserve_soc)

FOR each timestep t:

  PRIORITY 1 - Peak Shaving:
    IF net_load[t] > peak_limit_kw:
      energy_available = SOC[t] - SOC_min × E_nom  [FULL range]
      discharge[t] = min(required, P_max, available)
      SOC[t+1] = SOC[t] - discharge[t] / η_dis / Δt

  PRIORITY 2 - PV Surplus Charging:
    ELSE IF surplus > 0:
      charge[t] = min(surplus, P_max, space_to_SOC_max)
      SOC[t+1] = SOC[t] + charge[t] × η_charge × Δt
      curtailment[t] = surplus - charge[t]

  PRIORITY 3 - PV Shifting Discharge:
    ELSE IF deficit > 0:
      energy_above_reserve = SOC[t] - pv_soc_min  [ONLY above reserve]
      IF energy_above_reserve > 0:
        discharge[t] = min(deficit, available_above_reserve)
      grid_import[t] = deficit - discharge[t]
```

#### Per-Service Degradation Tracking

```
throughput_peak_mwh: Energy for peak shaving
throughput_pv_mwh: Energy for PV shifting
efc_peak: Cycles for peak shaving
efc_pv: Cycles for PV shifting
peak_events_count: Number of peak shaving events
```

### 3.4 ToU Arbitrage Dispatch

**Location:** `services/bess-dispatch/dispatch_arbitrage.py`

**Purpose:** Profit from energy price differences between zones/hours

#### Algorithm

```
charge_threshold = P25  [e.g., 300 PLN/MWh]
discharge_threshold = P75  [e.g., 600 PLN/MWh]

FOR each timestep t:
  price_t = import_prices[t]

  PRIORITY 1 - Peak Shaving (if peak_limit set):
    IF Load[t] > peak_limit:
      discharge to reduce peak

  PRIORITY 2 - Low Price Charging:
    ELSE IF price_t ≤ charge_threshold:
      charge_from_grid = min(P_max, available_space)
      grid_import[t] = Load[t] + charge_from_grid

  PRIORITY 3 - High Price Discharging:
    ELSE IF price_t > discharge_threshold AND SOC > SOC_min:
      discharge[t] = min(P_max, available_SOC)
      grid_export[t] OR reduce_import[t]

  ELSE (normal price):
    standard_dispatch (self-consumption or peak shaving)
```

---

## 4. BESS Sizing Algorithms

### 4.1 Heuristic Method (Fast)

**Location:** `services/economics/bess_optimizer.py`

**Purpose:** Quick estimation of BESS capacity and power

#### Methodology

```
1. Find exceedance blocks above peak_limit_kw
2. Identify largest block by energy

Capacity Calculation:
  E_bess = (E_max_block / (DOD × η)) × safety_margin
  where:
    E_max_block = energy of largest block [kWh]
    DOD = depth of discharge (0.8)
    η = round-trip efficiency (0.9)
    safety_margin = 1.2 (20% buffer)

Power Calculation:
  P_bess = max_excess_power × safety_margin
  where:
    max_excess_power = max(power - threshold) across all blocks [kW]
```

#### Example

```
Largest block: 920 kWh, max excess: 232 kW
E_bess = (920 / 0.72) × 1.2 = 1,533 kWh
P_bess = 232 × 1.2 = 278 kW
```

**Computation time:** <1ms per test point

### 4.2 PyPSA+HiGHS Optimization (Advanced)

**Location:** `services/economics/bess_optimizer.py`

**Purpose:** Optimal BESS sizing using linear programming

#### Optimization Model

```
Minimize: CAPEX = E × cost_kwh + P × cost_kw

Subject to:
  SOC(t) = SOC(t-1) + charge(t)×η - discharge(t)/η
  SOC_min ≤ SOC(t) ≤ SOC_max
  charge(t) ≤ P_max
  discharge(t) ≤ P_max
  discharge(t) ≥ excess(t)  [for all exceedance hours]
  SOC(0) = SOC(T)  [cyclicity]
```

#### Libraries Used

- **PyPSA** v0.27.1: Power system network optimization model
- **HiGHS** v1.7.1: High-performance LP/MIP solver

### 4.3 Grid Search Optimization (Iterative NPV)

**Location:** `services/bess-dispatch/sizing_runner.py`

**Purpose:** Find optimal power/duration combination maximizing NPV

#### Methodology

```
FOR each duration D in [1h, 2h, 4h]:
  power_range = linspace(min_power, max_power, 15 steps)

  FOR each power P in power_range:
    E = P × D

    IF E in [E_min, E_max]:
      1. Run dispatch simulation (8760 hours)
         → annual_discharge_kwh
         → grid_peak_kw
         → demand_charge_savings

      2. Calculate economics:
         capex = E × cost_kwh + P × cost_kw
         annual_opex = capex × opex_pct
         annual_savings = discharge × price + peak_savings + arbitrage
         npv = NPV(savings-opex, capex, discount_rate, years)

      3. If NPV > best_npv:
         save config
```

#### NPV Formula

```
NPV = Σ(t=1..n) [(annual_savings - opex) / (1+r)^t] - CAPEX

where:
  r = discount_rate (7%)
  n = analysis_period (25 years)
```

---

## 5. Economic Calculations

### 5.1 BESS Cost Analysis

**Location:** `services/bess-dispatch/economics_helper.py`

#### CAPEX Calculation

```
CAPEX = E_nom × capex_per_kwh + P_max × capex_per_kw

Default values:
  capex_per_kwh = 1500 PLN/kWh
  capex_per_kw = 300 PLN/kW

Example: 100 kW / 200 kWh
  CAPEX = 200 × 1500 + 100 × 300 = 330,000 PLN
```

#### OPEX Calculation

```
Annual OPEX = CAPEX × opex_pct_per_year

Default: opex_pct_per_year = 1.5%
Example: 330,000 × 0.015 = 4,950 PLN/year

Over 25 years: 4,950 × 25 = 123,750 PLN
```

### 5.2 Peak Shaving Savings

```
Monthly savings = peak_reduction_kw × demand_charge_pln_kw_month
Annual savings = monthly_savings × 12

Example:
  Original peak: 1200 kW
  New peak (after BESS): 1000 kW
  Peak reduction: 200 kW
  Demand charge: 50 PLN/kW/month
  Monthly savings: 200 × 50 = 10,000 PLN
  Annual savings: 120,000 PLN
```

### 5.3 Peak Shaving vs Contractual Penalty Analysis

**Location:** `services/frontend-economics/consumption.js` (lines 2139-2308)

#### Penalty Calculation (Polish Tariff)

```
Penalty = C_ss × sum(TOP10 exceedances/month)

where:
  C_ss = fixed component of network tariff [PLN/kW/month]
         (typically 40 PLN/kW/month for TAURON/PGE B21)
  TOP10 = 10 largest hourly exceedances above P_um per month [kW]

Algorithm:
1. For each month:
   - Get all hourly excess values: excess[h] = max(0, power[h] - P_um)
   - Sort descending
   - Take top 10 values
   - Sum them: sum_top10

2. Monthly penalty = C_ss × sum_top10

3. Annual penalty = Σ(all months) monthly_penalty

4. Over 15 years: annual_penalty × 15
```

#### Decision Logic

```
IF (BESS_COST_15Y < PENALTY_COST_15Y):
  → Invest in BESS
  savings = PENALTY_COST_15Y - BESS_COST_15Y
ELSE:
  → Pay penalty
  savings = BESS_COST_15Y - PENALTY_COST_15Y
```

---

## 6. Degradation Models

### 6.1 Cycle Accounting (Equivalent Full Cycles - EFC)

**Location:** `services/bess-dispatch/cycle_accounting_helper.py`

#### Formula

```
EFC = total_discharge_kwh / usable_capacity_kwh

Usable capacity:
  E_usable = E_nom × (SOC_max - SOC_min)
  E_usable = E_nom × (0.90 - 0.10) = 0.80 × E_nom

Example:
  E_nom = 200 kWh
  E_usable = 160 kWh
  Annual discharge = 40,000 kWh
  Annual EFC = 40,000 / 160 = 250 cycles/year
```

### 6.2 Degradation Budget Check

**Location:** `services/bess-dispatch/dispatch_engine.py`

#### Methodology

```
cycle_life = 6000 cycles (typical)
calendar_life = 15 years
degradation_year1 = 3%
degradation_per_year = 1.5% (years 2+)

Annual cycles allowed = cycle_life / expected_lifetime_years

For STACKED mode:
  - Separate cycle budgets for peak shaving vs PV shifting
  - Track cumulative cycles per service
  - Alert if exceeded
```

### 6.3 Battery Capacity Degradation Over Time

```
Capacity(year_n) = Capacity(0) × (1 - degradation_rate)^n

Example with 1.5%/year degradation:
  Year 0:  200 kWh (100%)
  Year 1:  194 kWh (97%)  - including initial 3% Y1 loss
  Year 5:  182.5 kWh (91.2%)
  Year 10: 169 kWh (84.5%)
  Year 15: 156.3 kWh (78.1%)

Impact on annual energy:
  annual_discharge(year_n) = annual_discharge(0) × capacity_factor(n)
```

---

## 7. Tariff Optimization

### 7.1 OSD Tariff System (Polish Distribution Tariffs)

**Location:** `services/bess-dispatch/osd_tariffs/compiler.py`

#### Tariff Structure

```
OSD Tariff Components:
  1. Variable (Zmienny) - time-varying cost [PLN/kWh]
  2. Fixed (Stały) - constant monthly cost [PLN]
  3. Capacity Fee (Opłata mocowa) - demand charge [PLN/kW/month]
  4. Transmission (Opłata przesyłowa) - grid access [PLN]

Zone-Based Pricing (3-zone system):
  Zone I (expensive): Peak hours (7-21 weekdays)
  Zone II (medium): Shoulder hours
  Zone III (cheap): Off-peak (21-7, weekends)
```

#### Tariff Compiler Algorithm

```
1. Load tariff definition with schedules per date range
2. For each date:
   - Determine day type (workday/weekend/holiday)
   - Get active schedule for this date
   - For each minute: map to zone (I/II/III)
   - For each hour: take majority vote zone
   - Calculate rate from zone

3. Compile day: (date, day_type, minute_zones[], hourly_zones[], hourly_rates[])
4. Cache results for performance
```

---

## 8. Capacity Fee (Polish Market)

### 8.1 Capacity Fee Calculation Algorithm

**Location:** `services/bess-dispatch/capacity_fee_pl/calculator.py`

**Purpose:** Calculate capacity fee savings from BESS reducing grid import peaks

#### K-Class Classification

```
Δs = (avg_selected / avg_outside - 1) × 100%

where:
  selected = working hours 7:00-22:00
  outside = off-peak hours

K1: Δs < 5%           → A = 0.17
K2: Δs ∈ [5%, 10%)    → A = 0.50
K3: Δs ∈ [10%, 15%)   → A = 0.83
K4: Δs ≥ 15% OR ZPS=0 → A = 1.00
```

#### Fee Formula

```
WOM = A × SOM × ZS

where:
  A = class coefficient
  SOM = average power in selected hours [kW]
  ZS = tariff rate [PLN/kW]
```

#### BESS Impact

```
original_fee = A_original × SOM_original × ZS
new_fee = A_new × SOM_new × ZS
savings = original_fee - new_fee
```

---

## 9. Monte Carlo Simulation

### 9.1 Stochastic Simulation Engine

**Location:** `services/economics/monte_carlo/`

**Purpose:** Assess financial risk by simulating uncertain parameters

#### Simulated Parameters (NumPy vectorized)

```
1. Electricity Price: Normal(base=450 PLN/MWh, σ=15%)
2. Production Factor: Normal(base=1.0, σ=10%)
3. CAPEX: Lognormal(base=3500 PLN/kWp, σ=10%)
4. Inflation: Normal(base=2.5%, σ=2pp)
5. Degradation: Triangular(min=0.3%, mode=0.5%, max=0.8%)
6. Discount Rate: Triangular(min=5%, mode=7%, max=10%)
```

#### Correlation Matrix (Cholesky Decomposition)

```
          Price  Prod  CAPEX  Inflation
Price     1.00   0.00  -0.00  0.60
Prod      0.00   1.00  -0.20  -0.00
CAPEX    -0.00  -0.20   1.00  -0.00
Inflation 0.60  -0.00  -0.00  1.00
```

#### Algorithm

```
FOR each of N_simulations (typically 5,000-10,000):
  1. Generate correlated parameter samples
  2. For each year (1..25):
     - Apply degradation: capacity(year) × degrad_factor
     - Apply inflation: price(year) × (1+inflation)^year
     - Calculate cash flow: savings - opex
     - NPV contribution: CF / (1+discount_rate)^year
  3. Sum NPV contributions
  4. Estimate IRR (Newton-Raphson method)
  5. Calculate payback period

OUTPUT:
  - NPV distribution (mean, std, P10, P50, P90)
  - IRR distribution
  - Payback distribution
  - Risk metrics: VaR, CVaR, probability of positive NPV
```

#### Vectorization (NumPy Broadcasting)

```python
All N simulations in parallel:
  npv_results = -investments.copy()  # shape: (N,)
  FOR year in range(1, 26):
    degrad = (1 - degradation) ** year  # shape: (N,)
    production = base_prod × degrad × prod_factors  # shape: (N,)
    price = prices × (1 + inflation) ** year  # shape: (N,)
    savings = (production × price_discount)  # shape: (N,)
    npv_results += savings / ((1+discount)^year)
```

**Computation time:** ~20ms for 10,000 simulations

### 9.2 Risk Metrics

```
1. Probability Positive NPV = count(NPV > 0) / N_simulations

2. VaR (Value at Risk):
   VaR_95 = percentile(NPV, 5)  [95% confidence]

3. CVaR (Conditional VaR / Expected Shortfall):
   CVaR_95 = mean(NPV | NPV ≤ VaR_95)

4. Coefficient of Variation:
   CV = std(NPV) / abs(mean(NPV))

5. Sharpe Ratio:
   Sharpe = mean(NPV) / std(NPV)
```

---

## 10. Grid Constraints

### 10.1 Export Cap Constraint

**Location:** `services/bess-dispatch/dispatch_engine.py`

**Purpose:** Limit PV export for 0-export or reduced-export models

#### Algorithm

```
IF max_export_kw is set OR allow_export = False:
  FOR each timestep t:
    IF grid_export[t] > max_export_kw:
      excess = grid_export[t] - max_export_kw
      grid_export[t] = max_export_kw
      curtailment[t] += excess  [convert to curtail]
```

### 10.2 Import Cap Constraint

**Location:** `services/bess-dispatch/dispatch_engine.py`

**Purpose:** Respect maximum grid import limit

#### Algorithm

```
IF max_import_kw is set:
  FOR each timestep t:
    IF grid_import[t] > max_import_kw:
      unserved = grid_import[t] - max_import_kw
      grid_import[t] = max_import_kw
      track unserved_load_kwh
```

---

## 11. Revenue Stacking

### 11.1 Multi-Service BESS (STACKED Mode)

**Primary Strategy:** Use single battery for multiple revenue streams:

1. **PV Shifting (Self-consumption):** Charge from PV surplus, discharge during deficit
2. **Peak Shaving:** Reduce grid import peaks to lower demand charges
3. **ToU Arbitrage:** Charge on low prices, discharge on high prices (future)
4. **Capacity Fee Savings:** Reduce selected-hours average to lower capacity market fee

#### Implementation

- STACKED mode with SOC reserve allocation
- Separate degradation tracking per service (efc_pv, efc_peak)
- Per-service energy accounting (throughput_pv_mwh, throughput_peak_mwh)

### 11.2 Degradation Attribution

```
For each service:
  throughput[service] = total_energy_through_battery_for_service
  efc[service] = throughput[service] / usable_capacity

Total degradation:
  weighted_efc = efc_pv × pv_weight + efc_peak × peak_weight
```

---

## 12. Technology Stack

### Backend

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Main language |
| FastAPI | latest | REST API |
| Pydantic | latest | Validation |
| NumPy | latest | Vectorized math |
| PyPSA | 0.27.1 | Power system modeling |
| HiGHS | 1.7.1 | Optimization solver |

### Frontend

| Technology | Purpose |
|------------|---------|
| JavaScript | Main language (vanilla) |
| Chart.js | Visualization |
| HTML/CSS | User interface |

---

## File Locations Summary

| Algorithm | File | Location |
|-----------|------|----------|
| Peak Shaving Analysis | consumption.js | services/frontend-economics/~2139 |
| PV-Surplus Dispatch | dispatch_engine.py | services/bess-dispatch/~347 |
| Peak Shaving Dispatch | dispatch_engine.py | services/bess-dispatch/~450 |
| STACKED Dispatch | dispatch_engine.py | services/bess-dispatch/~550 |
| ToU Arbitrage | dispatch_arbitrage.py | services/bess-dispatch/~40 |
| BESS Sizing (Heuristic) | bess_optimizer.py | services/economics/~192 |
| BESS Sizing (PyPSA) | bess_optimizer.py | services/economics/~250 |
| Grid Search Optimization | sizing_runner.py | services/bess-dispatch/~138 |
| NPV Calculation | sizing_runner.py | services/bess-dispatch/~138 |
| Capacity Fee | calculator.py | services/bess-dispatch/capacity_fee_pl/~87 |
| OSD Tariff Compiler | compiler.py | services/bess-dispatch/osd_tariffs/~54 |
| Price Engine | price_engine.py | services/bess-dispatch/~82 |
| Cycle Accounting | cycle_accounting_helper.py | services/bess-dispatch/~50 |
| Monte Carlo Engine | engine.py | services/economics/monte_carlo/ |
| Degradation Budget | dispatch_engine.py | services/bess-dispatch/ |

---

## Related Documentation

- [BESS Peak Shaving Algorithm Full](BESS_Peak_Shaving_Algorithm_FULL.md)
- [BESS vs Penalty Calculation](BESS_vs_Penalty_Calculation.md)
- [Monte Carlo Technical Documentation](MONTE_CARLO_DOKUMENTACJA_TECHNICZNA.md)

---

*Documentation generated: January 2026*
