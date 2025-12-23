# BESS Module Technical Documentation
## Battery Energy Storage System

**Version:** 3.4
**Date:** 2025-12-23
**Author:** Analizator PV

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [BESS Operating Modes](#2-bess-operating-modes)
3. [Capacity Sizing Algorithms](#3-capacity-sizing-algorithms)
4. [Dispatch Simulation (Control)](#4-dispatch-simulation-control)
5. [Economic Calculations](#5-economic-calculations)
6. [Technical Parameters](#6-technical-parameters)
7. [API and Endpoints](#7-api-and-endpoints)
8. [Calculation Examples](#8-calculation-examples)
9. [Future Development - Discharge Strategies](#9-future-development---bess-discharge-strategies)
10. [Detailed Algorithm Description](#10-detailed-algorithm-description)

---

## 1. System Overview

### 1.1 BESS Module Architecture

The BESS system consists of the following components:

```
┌─────────────────────────────────────────────────────────────────┐
│                       BESS MODULES                              │
├─────────────────┬─────────────────┬─────────────────────────────┤
│  pv-calculation │    economics    │      profile-analysis       │
│  (auto_size_    │ (bess_optimizer │   (simulate_bess_universal) │
│   bess_lite)    │    .py)         │                             │
├─────────────────┼─────────────────┼─────────────────────────────┤
│  LIGHT Mode     │  Peak Shaving   │   Self-consumption +        │
│  Self-consump.  │  PyPSA+HiGHS    │   Peak Shaving +            │
│                 │                 │   Price Arbitrage           │
└─────────────────┴─────────────────┴─────────────────────────────┘
```

### 1.2 Main Functions

| Function | Module | Description |
|----------|--------|-------------|
| `auto_size_bess_lite()` | pv-calculation | BESS sizing for self-consumption (LIGHT mode) |
| `optimize_bess()` | economics | BESS sizing for peak shaving (LP/MIP) |
| `simulate_pv_system_with_bess()` | pv-calculation | Hourly PV+BESS simulation |
| `simulate_bess_universal()` | profile-analysis | Simulation with peak shaving and arbitrage |

---

## 2. BESS Operating Modes

### 2.1 LIGHT Mode (Self-Consumption)

**Goal:** Maximize self-consumption of PV energy in a 0-Export model.

**Operation:**
- PV surplus → battery charging
- Energy deficit → battery discharge
- Full battery + surplus → curtailment (loss)
- Deficit > BESS capacity → grid import

**Sizing algorithm (iterative NPV):**

```python
# Test power range: 10% to 100% of 75th percentile surplus
p_max_candidate = percentile(surplus, 75)
power_steps = linspace(p_max_candidate * 0.1, p_max_candidate, 10)

for each power in power_steps:
    energy = power * duration_hours
    annual_discharge = simulate_quick_dispatch(power, energy)
    annual_savings = annual_discharge * energy_price
    capex = power * capex_per_kw + energy * capex_per_kwh
    annual_cost = capex * annuity_factor
    npv = (annual_savings - annual_cost) / annuity_factor

    if npv > best_npv:
        best_power, best_energy = power, energy
```

### 2.2 PRO Mode (LP/MIP Optimization)

**Goal:** Optimal BESS sizing using optimization solvers.

**Libraries:**
- **PyPSA** (Python for Power System Analysis) v0.27.1
- **HiGHS** (High-performance LP/MIP solver) v1.7.1

**Optimization model:**

```
Minimize: CAPEX = E * capex_per_kwh + P * capex_per_kw

Constraints:
  SOC(t) = SOC(t-1) + charge(t) × η - discharge(t) / η
  SOC_min ≤ SOC(t) ≤ SOC_max
  charge(t) ≤ P
  discharge(t) ≤ P
  discharge(t) ≥ excess(t)   for each exceedance hour
  SOC(0) = SOC(T)            (cyclicity)
```

### 2.3 Peak Shaving

**Goal:** Reduce power peaks to lower demand charges.

**Parameters:**
- `peak_shaving_threshold_kw` - power threshold [kW]
- `power_charge_pln_per_kw_month` - demand charge [PLN/kW/month]

**Exceedance block grouping algorithm:**

```python
def group_exceedance_blocks(load_profile, threshold):
    blocks = []
    current_block = None

    for i, power in enumerate(load_profile):
        excess = power - threshold

        if excess > 0:
            if current_block is None:
                current_block = {'start': i, 'powers': [], 'excesses': []}
            current_block['powers'].append(power)
            current_block['excesses'].append(excess)
        else:
            if current_block is not None:
                # Close block
                block = BESSBlock(
                    duration_hours = len(current_block['powers']),
                    total_energy_kwh = sum(excesses) * hours_per_interval,
                    max_excess_kw = max(excesses)
                )
                blocks.append(block)
                current_block = None

    return blocks
```

**Sizing heuristic:**

```
Capacity = (largest block energy / efficiency) / DOD × margin
Power = max_deficit × margin
```

### 2.4 Price Arbitrage

**Goal:** Buy energy when cheap, sell when expensive.

**Parameters:**
- `buy_threshold_pln_mwh` - buy threshold (e.g., 300 PLN/MWh)
- `sell_threshold_pln_mwh` - sell threshold (e.g., 600 PLN/MWh)

**Logic:**
```
if price < buy_threshold AND soc < soc_max:
    charge from grid
elif price > sell_threshold AND soc > soc_min:
    discharge to grid (or load)
```

---

## 3. Capacity Sizing Algorithms

### 3.1 Heuristic Method (LIGHT)

**Location:** `pv-calculation/app.py` → `auto_size_bess_lite()`

**Steps:**
1. Calculate surplus profile: `surplus = PV_production - direct_consumption`
2. Determine test power range: `10% - 100%` of 75th percentile surplus
3. For each test power:
   - Calculate capacity: `energy = power × duration`
   - Simulate dispatch and calculate annual discharge
   - Calculate NPV
4. Select configuration with highest NPV

**NPV formula:**

```
annuity_factor = (r × (1+r)^n) / ((1+r)^n - 1)

where:
  r = discount rate (e.g., 7%)
  n = analysis period (e.g., 15 years)

annual_savings = annual_discharge × energy_price
annual_cost = CAPEX × annuity_factor
NPV = (annual_savings - annual_cost) / annuity_factor
```

### 3.2 PyPSA+HiGHS Method (PRO)

**Location:** `economics/bess_optimizer.py` → `optimize_bess_pypsa()`

**PyPSA model:**

```python
network = pypsa.Network()
network.set_snapshots(range(n_hours))

# Bus
network.add("Bus", "main_bus")

# Load (excess above threshold)
network.add("Load", "peak_excess",
            bus="main_bus",
            p_set=excess)

# Energy storage with optimized capacity
network.add("Store", "bess",
            bus="main_bus",
            e_nom_extendable=True,      # Optimize capacity
            e_nom_min=0,
            e_nom_max=1e6,
            e_min_pu=soc_min,           # Min SOC
            e_max_pu=soc_max,           # Max SOC
            e_cyclic=True,              # SOC(0) = SOC(T)
            capital_cost=capex_per_kwh)

# Solve optimization
status = network.optimize(solver_name="highs")
optimal_capacity = network.stores.loc["bess", "e_nom_opt"]
```

### 3.3 Method Comparison

| Aspect | Heuristic | LP (PyPSA) | MIP (PyPSA) |
|--------|-----------|------------|-------------|
| Computation time | <1 ms | 10-100 ms | 100 ms - 1 s |
| Accuracy | Good | Optimal | Highest |
| Requirements | None | PyPSA+HiGHS | PyPSA+HiGHS |
| Application | Quick estimates | Production | Final projects |

---

## 4. Dispatch Simulation (Control)

### 4.1 Greedy Algorithm

**Location:** `pv-calculation/app.py` → `simulate_pv_system_with_bess()`

**Pseudocode:**

```python
for each hour h:
    pv = production[h]
    load = consumption[h]

    # Step 1: Direct self-consumption
    direct = min(pv, load)
    surplus = pv - direct
    deficit = load - direct

    # Step 2: Handle surplus (charge or curtailment)
    if surplus > 0:
        charge_power = min(surplus, bess_power_kw)
        available_space = soc_max_kwh - soc
        charge_energy = min(charge_power * η, available_space)

        soc += charge_energy
        curtailed = surplus - (charge_energy / η)

    # Step 3: Handle deficit (discharge or import)
    if deficit > 0:
        discharge_power = min(deficit, bess_power_kw)
        available_energy = soc - soc_min_kwh
        discharge_from_soc = min(discharge_power / η, available_energy)
        discharge_delivered = discharge_from_soc * η

        soc -= discharge_from_soc
        grid_import = deficit - discharge_delivered
```

### 4.2 Charge/Discharge Efficiency

**One-way efficiency:**

```
η_one_way = √(η_roundtrip)

Example: η_roundtrip = 90% → η_one_way = 94.87%
```

**Energy losses:**
- Charging: `E_stored = E_input × η_one_way`
- Discharging: `E_output = E_stored × η_one_way`
- Combined: `E_output = E_input × η_roundtrip`

### 4.3 Cycle Calculation

```python
# Annual equivalent cycles
annual_cycles = total_discharged_kwh / usable_capacity_kwh

where:
  usable_capacity = bess_energy_kwh × (soc_max - soc_min)
  usable_capacity = bess_energy_kwh × (0.9 - 0.1) = 0.8 × bess_energy_kwh
```

---

## 5. Economic Calculations

### 5.1 CAPEX (Capital Expenditure)

```
CAPEX = (capacity × capex_per_kwh) + (power × capex_per_kw)

Default values:
  capex_per_kwh = 1500 PLN/kWh
  capex_per_kw = 300 PLN/kW

Example: 100 kW / 200 kWh
  CAPEX = 200 × 1500 + 100 × 300 = 330,000 PLN
```

### 5.2 OPEX (Operating Expenditure)

```
OPEX_annual = CAPEX × opex_pct_per_year

Default: opex_pct_per_year = 1.5%

Example:
  OPEX = 330,000 × 0.015 = 4,950 PLN/year
```

### 5.3 NPV (Net Present Value)

```
NPV = Σ(t=1 to n) [(savings_t - opex_t) / (1+r)^t] - CAPEX

where:
  savings_t = annual_discharge × energy_price × degradation_factor(t)
  r = discount rate
  n = analysis period
```

### 5.4 Simple Payback Period

```
Payback = CAPEX / annual_savings

Example:
  CAPEX = 330,000 PLN
  annual_savings = 50,000 PLN/year
  Payback = 330,000 / 50,000 = 6.6 years
```

### 5.5 BESS LCOE (Levelized Cost of Energy)

```
LCOE = (CAPEX + Σ OPEX_discounted) / (Σ Energy_discharged_discounted)

Unit: PLN/MWh
```

### 5.6 Peak Shaving Savings

```
monthly_savings = peak_reduction_kw × power_charge_pln_per_kw
annual_savings = monthly_savings × 12

where:
  peak_reduction_kw = original_peak - new_peak
  power_charge_pln_per_kw = demand charge (e.g., 50 PLN/kW/month)
```

---

## 6. Technical Parameters

### 6.1 SOC (State of Charge) Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `soc_min` | 10% | 0-50% | Minimum depth of discharge |
| `soc_max` | 90% | 50-100% | Maximum state of charge |
| `soc_initial` | 50% | 10-90% | Initial state of charge |
| `DOD` | 80% | 50-100% | Depth of discharge (soc_max - soc_min) |

### 6.2 Efficiency Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `roundtrip_efficiency` | 90% | 70-98% | Charge→discharge cycle efficiency |
| `standing_loss` | 0.01% | 0-1% | Standing losses per hour |
| `auxiliary_loss_pct_per_day` | 0.1% | 0-1% | Auxiliary losses per day |

### 6.3 Lifetime Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `cycle_life` | 6000 | 1000-10000 | Cycle lifetime |
| `calendar_life_years` | 15 | 5-25 | Calendar lifetime |
| `degradation_year1_pct` | 3.0% | 0-10% | First year degradation |
| `degradation_pct_per_year` | 1.5% | 0-5% | Annual degradation (subsequent years) |

### 6.4 C-Rate Parameters

```
C-rate = Power_kW / Capacity_kWh

Examples:
  C-rate = 1.0  → 100 kW / 100 kWh → full discharge in 1h
  C-rate = 0.5  → 50 kW / 100 kWh → full discharge in 2h
  C-rate = 2.0  → 200 kW / 100 kWh → full discharge in 0.5h
```

| Duration | C-rate | Application |
|----------|--------|-------------|
| 1h | 1.0 | Peak shaving |
| 2h | 0.5 | Self-consumption (standard) |
| 4h | 0.25 | Price arbitrage, backup |

---

## 7. API and Endpoints

### 7.1 Endpoint: `/bess/optimize`

**Method:** POST
**Module:** economics

**Request:**
```json
{
  "load_profile_kw": [100, 120, 150, ...],
  "timestamps": ["2024-01-01T00:00:00", ...],
  "interval_minutes": 60,
  "peak_shaving_threshold_kw": 500,
  "bess_capex_per_kwh": 1500,
  "bess_capex_per_kw": 300,
  "depth_of_discharge": 0.8,
  "round_trip_efficiency": 0.90,
  "max_c_rate": 1.0,
  "method": "lp_relaxed"
}
```

**Response:**
```json
{
  "optimal_capacity_kwh": 200.0,
  "optimal_power_kw": 100.0,
  "capex_total_pln": 330000,
  "annual_opex_pln": 4950,
  "usable_capacity_kwh": 160.0,
  "total_annual_cycles": 250,
  "expected_lifetime_years": 15,
  "sizing_rationale": "PyPSA+HiGHS LP: optimal capacity 200 kWh...",
  "warnings": []
}
```

### 7.2 Endpoint: `/analyze` (with BESS)

**Method:** POST
**Module:** pv-calculation

**Request with BESS LIGHT:**
```json
{
  "consumption": [50, 60, 70, ...],
  "timestamps": ["2024-01-01T00:00:00", ...],
  "pv_config": {...},
  "bess_config": {
    "enabled": true,
    "mode": "light",
    "duration": "2",
    "roundtrip_efficiency": 0.90,
    "soc_min": 0.10,
    "soc_max": 0.90,
    "capex_per_kwh": 1500,
    "capex_per_kw": 300
  }
}
```

### 7.3 Endpoint: `/bess/methods`

**Method:** GET
**Module:** economics

**Response:**
```json
{
  "heuristic": {
    "name": "Heuristic",
    "description": "Fast method based on largest overload block",
    "pros": ["Very fast (<1ms)", "No solver required"],
    "cons": ["May give oversized results"]
  },
  "lp_relaxed": {
    "name": "LP (PyPSA+HiGHS)",
    "description": "Linear optimization with PyPSA and HiGHS solver",
    "pros": ["Optimal solution", "Fast (10-100ms)"]
  },
  "mip_full": {
    "name": "MIP (PyPSA+HiGHS)",
    "description": "Full mixed-integer programming optimization"
  }
}
```

---

## 8. Calculation Examples

### 8.1 Example: BESS Sizing for Self-Consumption

**Input data:**
- Annual PV production: 1,200 MWh
- Annual consumption: 1,000 MWh
- Self-consumption without BESS: 600 MWh (50%)
- PV surplus: 600 MWh
- Energy price: 800 PLN/MWh

**Calculations:**
```
1. 75th percentile of hourly surplus: 150 kW
2. Test range: 15 kW - 150 kW (10 steps)
3. Duration: 2h → Energy = Power × 2

For Power = 75 kW, Energy = 150 kWh:
  - Annual discharge: ~180 MWh
  - Annual savings: 180 × 0.8 = 144,000 PLN
  - CAPEX: 150 × 1500 + 75 × 300 = 247,500 PLN
  - Annuity factor (7%, 15 years): 0.1098
  - Annual cost: 247,500 × 0.1098 = 27,175 PLN
  - NPV: (144,000 - 27,175) / 0.1098 = 1,064,000 PLN

Optimal sizing: 75 kW / 150 kWh
```

### 8.2 Example: Peak Shaving

**Input data:**
- Peak power: 1,200 kW
- Peak shaving threshold: 1,000 kW
- Demand charge: 50 PLN/kW/month

**Exceedance block analysis:**
```
Block 1: 14:00-16:00, max 1150 kW, energy 250 kWh
Block 2: 18:00-19:00, max 1100 kW, energy 80 kWh
Block 3: 10:00-11:00, max 1080 kW, energy 60 kWh

Largest block: 250 kWh, max excess: 150 kW
```

**BESS sizing (heuristic):**
```
Capacity = (250 / 0.90) / 0.8 × 1.2 = 416 kWh
Power = 150 × 1.2 = 180 kW

C-rate check: 180 / 416 = 0.43 < 1.0 ✓
```

**Savings:**
```
Peak reduction: 1200 - 1000 = 200 kW
Monthly savings: 200 × 50 = 10,000 PLN
Annual savings: 120,000 PLN
```

### 8.3 Example: Degradation Model

**Parameters:**
- Initial capacity: 200 kWh
- Year 1 degradation: 3%
- Subsequent years degradation: 1.5%/year
- Analysis period: 15 years

**Capacity calculations:**
```
Year 0:  200.0 kWh (100%)
Year 1:  194.0 kWh (97%)
Year 2:  191.1 kWh (95.5%)
Year 5:  182.5 kWh (91.2%)
Year 10: 169.0 kWh (84.5%)
Year 15: 156.3 kWh (78.1%)
```

**Impact on annual energy:**
```
Year 1:  energy × 0.97
Year 5:  energy × 0.912
Year 10: energy × 0.845
Year 15: energy × 0.781
```

---

## Appendices

### A. File Structure

```
services/
├── pv-calculation/
│   └── app.py
│       ├── auto_size_bess_lite()      # LIGHT sizing
│       ├── simulate_pv_system_with_bess()  # Simulation
│       └── BESSConfigLite             # Configuration model
│
├── economics/
│   ├── app.py
│   │   ├── /bess/optimize             # Optimization endpoint
│   │   └── /bess/methods              # Methods endpoint
│   └── bess_optimizer.py
│       ├── optimize_bess()            # Main function
│       ├── optimize_bess_heuristic()  # Heuristic method
│       ├── optimize_bess_pypsa()      # LP/MIP method
│       └── group_exceedance_blocks()  # Block grouping
│
├── profile-analysis/
│   └── app.py
│       ├── simulate_bess_universal()  # Universal simulation
│       └── calculate_bess_recommendations()
│
└── frontend-bess/
    ├── bess.js                        # UI logic
    ├── index.html                     # Interface
    └── styles.css                     # Styles
```

### B. Dependencies

```
PyPSA==0.27.1          # Power system modeling
highspy==1.7.1         # LP/MIP solver
numpy>=1.26.2          # Numerical computations
pandas>=2.1.3          # Data handling
```

### C. Glossary

| Term | Description |
|------|-------------|
| **SOC** | State of Charge - battery charge level (0-100%) |
| **DOD** | Depth of Discharge - discharge depth |
| **C-rate** | Power to capacity ratio |
| **Curtailment** | Wasted energy (could not be utilized) |
| **Peak Shaving** | Power peak reduction |
| **Arbitrage** | Buy cheap, sell expensive |
| **Roundtrip Efficiency** | Full charge→discharge cycle efficiency |
| **CAPEX** | Capital Expenditure - investment cost |
| **OPEX** | Operating Expenditure - operational costs |
| **NPV** | Net Present Value |
| **LCOE** | Levelized Cost of Energy |

---

## 9. Future Development - BESS Discharge Strategies

### 9.1 Current Strategy (Reactive)

The system currently uses a **reactive (greedy) strategy**:

```
1. Charge storage when there is PV surplus (surplus = PV - Load > 0)
2. Discharge storage when there is deficit (deficit = Load - PV > 0)
3. Discharge occurs immediately upon detecting deficit
4. No "waiting" to reach 90% SOC before discharging
```

**Advantages:**
- Simple implementation
- Immediate response to deficit
- Maximizes self-consumption at any given moment

**Disadvantages:**
- No global (daily/weekly) optimization
- May discharge storage before evening peak
- Does not consider day profile prediction

### 9.2 Predictive Strategy (Predictive Dispatch)

**Concept:** Knowing the PV and consumption profile in advance (or forecast), optimize discharge for the entire day.

```python
def predictive_dispatch(pv_forecast, load_forecast, battery):
    """
    Forward-looking discharge optimization.

    1. Calculate total daily deficit: total_deficit = Σ max(0, load - pv)
    2. Calculate available BESS energy: available_energy = (soc_max - soc_min) × capacity
    3. Set uniform discharge level or focus on peak hours
    """
    daily_deficit_hours = get_deficit_hours(pv_forecast, load_forecast)
    energy_per_hour = min(
        available_energy / len(daily_deficit_hours),
        battery.power_kw
    )

    discharge_schedule = {}
    for hour in daily_deficit_hours:
        discharge_schedule[hour] = energy_per_hour

    return discharge_schedule
```

**Requirements:**
- PV forecast (can use historical PVGIS data)
- Consumption forecast (typical day profile)
- Optimization solver or heuristic

**Application:**
- Systems with weather forecast access
- Industrial installations with stable consumption profile

### 9.3 Higher Discharge Threshold (Threshold-Based Discharge)

**Concept:** Don't discharge storage for small deficits - save energy for larger peaks.

```python
def threshold_dispatch(pv, load, battery, min_deficit_threshold_kw=10):
    """
    Discharge only when deficit exceeds threshold.

    Parameters:
    - min_deficit_threshold_kw: minimum deficit for discharge

    Effect:
    - Small deficits covered by grid (cheap import)
    - Large deficits covered by storage
    """
    deficit = load - pv

    if deficit > min_deficit_threshold_kw:
        # Discharge to cover deficit
        discharge = min(deficit, battery.power_kw, available_soc)
    else:
        # Small deficit - grid import
        discharge = 0
        grid_import = deficit

    return discharge, grid_import
```

**Configurable parameters:**
- `min_deficit_threshold_kw` - minimum deficit threshold (e.g., 10 kW)
- `priority_hours` - priority discharge hours (e.g., 17:00-21:00)

**Application:**
- Systems with demand charges (peak shaving)
- Situations where small grid import is cheaper than BESS cycle usage

### 9.4 Even Discharge Distribution

**Concept:** Discharge storage evenly across all deficit hours instead of reactively.

```python
def even_distribution_dispatch(pv_day, load_day, battery):
    """
    Distribute discharge evenly throughout the day.

    Step 1: Identify deficit hours (load > pv)
    Step 2: Calculate total deficits
    Step 3: Set constant discharge power = min(total_deficit, capacity) / deficit_hours
    """
    deficit_hours = []
    total_deficit = 0

    for h in range(24):
        if load_day[h] > pv_day[h]:
            deficit_hours.append(h)
            total_deficit += load_day[h] - pv_day[h]

    # Energy to distribute
    available_energy = (battery.soc_max - battery.soc_min) * battery.energy_kwh
    energy_to_distribute = min(total_deficit, available_energy)

    # Even power per hour
    if len(deficit_hours) > 0:
        power_per_hour = energy_to_distribute / len(deficit_hours)
        power_per_hour = min(power_per_hour, battery.power_kw)
    else:
        power_per_hour = 0

    # Schedule
    discharge_schedule = {h: power_per_hour for h in deficit_hours}
    return discharge_schedule
```

**Advantages:**
- Predictable storage behavior
- Better protection against deep discharge
- Ability to reserve energy for evening peaks

**Disadvantages:**
- Requires knowing the entire day profile in advance
- May not fully utilize capacity

### 9.5 Evening Hours Priority

**Concept:** Save most energy for evening hours (17:00-21:00) when PV doesn't produce.

```python
def evening_priority_dispatch(pv, load, hour, battery, soc_current):
    """
    Priority discharge for evening hours.

    Rules:
    - Before 17:00: discharge only 30% of available energy
    - 17:00-21:00: discharge without restrictions
    - After 21:00: normal discharge
    """
    deficit = load - pv
    if deficit <= 0:
        return 0

    if hour < 17:
        # Before evening - limited discharge
        max_discharge_pct = 0.30
        reserved_soc = battery.soc_max * 0.7  # Reserve 70% for evening
        available = max(0, soc_current - reserved_soc)
    elif 17 <= hour <= 21:
        # Evening hours - full discharge
        max_discharge_pct = 1.0
        available = soc_current - battery.soc_min
    else:
        # After evening - normal discharge
        max_discharge_pct = 1.0
        available = soc_current - battery.soc_min

    discharge = min(deficit, battery.power_kw, available * max_discharge_pct)
    return discharge
```

**Parameters:**
- `evening_start_hour` - evening window start (e.g., 17)
- `evening_end_hour` - evening window end (e.g., 21)
- `reserve_fraction` - capacity fraction to reserve (e.g., 0.7)

### 9.6 Price-Based Strategy

**Concept:** Discharge when energy price is high, charge when low.

```python
def price_based_dispatch(pv, load, price, battery, soc):
    """
    Price-based dispatch (TOU - Time of Use).

    Price thresholds:
    - price < low_threshold: charge from grid (if cheap import)
    - price > high_threshold: discharge maximally
    - in between: normal self-consumption
    """
    LOW_PRICE_THRESHOLD = 300   # PLN/MWh
    HIGH_PRICE_THRESHOLD = 800  # PLN/MWh

    surplus = pv - load
    deficit = load - pv

    if price < LOW_PRICE_THRESHOLD and surplus <= 0:
        # Cheap energy - charge from grid
        charge = min(battery.power_kw, (battery.soc_max - soc) * battery.energy_kwh)
        grid_import = deficit + charge
        return 0, charge, grid_import

    elif price > HIGH_PRICE_THRESHOLD and deficit > 0:
        # Expensive energy - discharge maximally
        discharge = min(deficit, battery.power_kw, (soc - battery.soc_min) * battery.energy_kwh)
        return discharge, 0, deficit - discharge

    else:
        # Normal self-consumption
        # ... standard greedy logic
        pass
```

**Application:**
- Markets with dynamic energy prices (day-ahead market)
- Prosumers with dynamic tariffs

### 9.7 Hybrid Strategy (STACKED with Reserve)

**Current implementation in `dispatch_stacked()`:**

```python
def dispatch_stacked(pv, load, battery, params):
    """
    STACKED mode: PV surplus + Peak Shaving with SOC reserve.

    Rules:
    1. Reserve part of capacity (reserve_fraction) for peak shaving
    2. Rest available for PV surplus
    3. When exceeding peak_limit - use reserve
    """
    reserve_soc = battery.soc_min + (battery.soc_max - battery.soc_min) * params.reserve_fraction

    # For PV surplus: discharge only to reserve_soc
    # For Peak Shaving: discharge to soc_min
```

### 9.8 Strategy Comparison

| Strategy | Complexity | Requirements | Best for |
|----------|------------|--------------|----------|
| Reactive (Greedy) | Low | None | Simple installations |
| Predictive | High | PV/Load forecasts | Industrial |
| Discharge threshold | Low | Threshold parameter | Peak shaving |
| Even distribution | Medium | Day profile | Stable consumption |
| Evening priority | Medium | Time window | Homes, offices |
| Price-based | Medium | Price data | Arbitrage |
| STACKED | Medium | Peak threshold + reserve | Combined services |

### 9.9 Implementation Plan

**Phase 1: Strategy parameterization**
```python
class DispatchStrategy(Enum):
    GREEDY = "greedy"           # Current
    PREDICTIVE = "predictive"   # Future
    THRESHOLD = "threshold"     # Future
    EVENING = "evening"         # Future
    PRICE_BASED = "price"       # Future
    STACKED = "stacked"         # Current
```

**Phase 2: Strategy selection interface**
- Dropdown in BESS settings
- Parameters for each strategy

**Phase 3: Comparative visualization**
- Chart comparing different strategies
- Metrics: self-consumption, curtailment, cycles, NPV

---

## 10. Detailed Algorithm Description

### 10.1 Input Data Sources

#### PV Production Profile
```
Source: PVGIS API (Photovoltaic Geographical Information System)
URL: https://re.jrc.ec.europa.eu/api/v5_2/
Parameters: location (lat/lon), tilt angle, azimuth, module technology
Data: Typical Meteorological Year (TMY) - 8760 hourly values [kWh]
```

#### Energy Consumption Profile
```
Source: User upload (CSV/Excel) or standard profile
Format: 8760 hourly values [kWh] or 35040 quarter-hourly values
Validation: annual sum, min/max, no negative values
```

#### Energy Prices
```
Sources:
- TGE (Polish Power Exchange) - day-ahead/intraday prices
- Distribution tariffs (G11, G12, C11, C21, B21)
- User-defined contractual prices
Format: fixed price [PLN/MWh] or hourly profile
```

### 10.2 Grid Search Algorithm (Iterative NPV Optimization)

**Location:** `services/bess-optimizer/app.py` → `run_pypsa_optimization()`

#### Operation Scheme

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRID SEARCH OPTIMIZER                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INPUT DATA:                                                    │
│  ├── pv_generation_kwh[8760]  ← PV production profile          │
│  ├── load_kwh[8760]           ← Consumption profile            │
│  ├── min/max_power_kw         ← Power constraints              │
│  ├── min/max_energy_kwh       ← Capacity constraints           │
│  ├── duration_min/max_h       ← E/P ratio constraints          │
│  ├── capex_per_kw/kwh         ← Investment costs               │
│  ├── energy_price_plnmwh      ← Energy price                   │
│  └── discount_rate            ← Discount rate                  │
│                                                                 │
│  PRELIMINARY CALCULATIONS:                                      │
│  ├── net_load = load - pv     ← Energy balance                 │
│  ├── surplus = max(-net, 0)   ← PV surplus for charging        │
│  └── deficit = max(net, 0)    ← Deficit for discharging        │
│                                                                 │
│  SEARCH GRID:                                                   │
│  ├── power_range = linspace(min_power, max_power, 15)          │
│  └── duration_options = [min_h, (min+max)/2, max_h]            │
│                                                                 │
│  FOR EACH COMBINATION (power, duration):                        │
│  │   energy = power × duration                                  │
│  │   IF energy in range [min_energy, max_energy]:               │
│  │   │                                                          │
│  │   │   DISPATCH SIMULATION (8760 steps):                      │
│  │   │   └── dispatch = simulate_bess_dispatch(...)            │
│  │   │                                                          │
│  │   │   ECONOMIC CALCULATION:                                  │
│  │   │   ├── annual_savings = discharge × price                │
│  │   │   ├── capex = power×cost_kw + energy×cost_kwh           │
│  │   │   ├── annual_opex = capex × opex_pct                    │
│  │   │   └── npv = NPV(capex, savings-opex, rate, years)       │
│  │   │                                                          │
│  │   │   IF npv > best_npv:                                     │
│  │   │       best_config = (power, energy, dispatch)            │
│  │                                                              │
│  OUTPUT:                                                        │
│  ├── optimal_power_kw                                           │
│  ├── optimal_energy_kwh                                         │
│  ├── npv_bess_pln                                               │
│  ├── payback_years                                              │
│  ├── annual_cycles                                              │
│  └── hourly_soc[8760]                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Decision Variables

| Variable | Unit | Description | Typical Range |
|----------|------|-------------|---------------|
| `power_kw` | kW | BESS nominal power (charge/discharge) | 50 - 10,000 |
| `energy_kwh` | kWh | BESS nominal capacity | 100 - 50,000 |
| `duration_h` | h | E/P ratio (full discharge time) | 1 - 4 |

#### Constraints

```python
# Power and capacity constraints
min_power_kw <= power_kw <= max_power_kw
min_energy_kwh <= energy_kwh <= max_energy_kwh

# Duration constraint (E/P ratio)
duration_min_h <= energy_kwh / power_kw <= duration_max_h

# SOC constraints at each timestep
soc_min × energy_kwh <= soc[t] <= soc_max × energy_kwh

# Charge/discharge power constraints
charge[t] <= power_kw
discharge[t] <= power_kw
```

### 10.3 Dispatch Algorithm (Control Simulation)

**Location:** `services/bess-dispatch/dispatch_engine.py`

#### 10.3.1 PV-Surplus Algorithm (Self-Consumption)

```
┌─────────────────────────────────────────────────────────────────┐
│              DISPATCH PV-SURPLUS (GREEDY)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FOR EACH TIMESTEP t = 0..8759:                                 │
│                                                                 │
│  ┌─ STEP 1: Direct self-consumption ─────────────────────────┐ │
│  │  direct_pv[t] = min(pv[t], load[t])                       │ │
│  │  surplus = pv[t] - direct_pv[t]                           │ │
│  │  deficit = load[t] - direct_pv[t]                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ STEP 2: Handle PV surplus (charging) ────────────────────┐ │
│  │  IF surplus > 0:                                          │ │
│  │    charge_limit = min(surplus, P_max)                     │ │
│  │    space_available = SOC_max - SOC[t]                     │ │
│  │    charge_energy = min(charge_limit × η_ch × Δt, space)   │ │
│  │    charge[t] = charge_energy / (η_ch × Δt)                │ │
│  │    SOC[t+1] = SOC[t] + charge_energy                      │ │
│  │    curtailment[t] = surplus - charge[t]                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ STEP 3: Handle deficit (discharging) ────────────────────┐ │
│  │  IF deficit > 0:                                          │ │
│  │    discharge_limit = min(deficit, P_max)                  │ │
│  │    energy_available = SOC[t] - SOC_min                    │ │
│  │    max_from_soc = discharge_limit / η_dis × Δt            │ │
│  │                                                           │ │
│  │    IF max_from_soc > energy_available:                    │ │
│  │      actual_from_soc = energy_available                   │ │
│  │      discharge[t] = actual_from_soc × η_dis / Δt          │ │
│  │    ELSE:                                                  │ │
│  │      discharge[t] = discharge_limit                       │ │
│  │      actual_from_soc = max_from_soc                       │ │
│  │                                                           │ │
│  │    SOC[t+1] = SOC[t] - actual_from_soc                    │ │
│  │    grid_import[t] = deficit - discharge[t]                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 10.3.2 Peak Shaving Algorithm

```
┌─────────────────────────────────────────────────────────────────┐
│                  DISPATCH PEAK SHAVING                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PARAMETER: peak_limit_kw ← Peak power threshold               │
│                                                                 │
│  FOR EACH TIMESTEP t:                                           │
│                                                                 │
│    net_load[t] = load[t] - pv[t]                               │
│                                                                 │
│    ┌─ CASE 1: Threshold exceeded ─────────────────────────┐    │
│    │  IF net_load[t] > peak_limit_kw:                     │    │
│    │    required_discharge = net_load[t] - peak_limit_kw  │    │
│    │    discharge[t] = min(required, P_max, available_soc)│    │
│    │    grid_import[t] = net_load[t] - discharge[t]       │    │
│    │    new_peak = max(new_peak, grid_import[t])          │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│    ┌─ CASE 2: Below threshold, charging ──────────────────┐    │
│    │  IF 0 < net_load[t] <= peak_limit_kw:                │    │
│    │    headroom = peak_limit_kw - net_load[t]            │    │
│    │    IF headroom > 0 AND SOC < SOC_max:                │    │
│    │      charge[t] = min(headroom, P_max, space)         │    │
│    │      grid_import[t] = net_load[t] + charge[t]        │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│    ┌─ CASE 3: PV surplus ─────────────────────────────────┐    │
│    │  IF net_load[t] <= 0:                                │    │
│    │    surplus = -net_load[t]                            │    │
│    │    curtailment[t] = surplus  (0-export model)        │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│  RESULTS:                                                       │
│  ├── original_peak_kw = max(net_load > 0)                      │
│  ├── new_peak_kw = max(grid_import)                            │
│  └── peak_reduction_pct = (original - new) / original × 100    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 10.3.3 STACKED Algorithm (Hybrid)

```
┌─────────────────────────────────────────────────────────────────┐
│              DISPATCH STACKED (PV + PEAK SHAVING)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PARAMETERS:                                                    │
│  ├── peak_limit_kw     ← Peak shaving threshold                │
│  └── reserve_fraction  ← SOC fraction reserved for peak        │
│                                                                 │
│  SOC RESERVE CALCULATION:                                       │
│  reserve_soc = energy_kwh × reserve_fraction                    │
│  pv_soc_min = max(soc_min × energy, reserve_soc)               │
│                                                                 │
│  FOR EACH TIMESTEP t:                                           │
│                                                                 │
│    ┌─ PRIORITY 1: Peak Shaving ───────────────────────────┐    │
│    │  IF net_load[t] > peak_limit_kw:                     │    │
│    │    // Use FULL SOC (including reserve)               │    │
│    │    energy_available = SOC[t] - soc_min × energy      │    │
│    │    discharge_peak[t] = min(required, P_max, avail)   │    │
│    │    SOC[t+1] = SOC[t] - discharge_peak[t] / η         │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│    ┌─ PRIORITY 2: PV Shifting (surplus) ──────────────────┐    │
│    │  ELIF surplus > 0:                                   │    │
│    │    // Charge up to SOC_max                           │    │
│    │    charge_from_pv[t] = min(surplus, P_max, space)    │    │
│    │    SOC[t+1] = SOC[t] + charge × η                    │    │
│    │    curtailment[t] = surplus - charge                 │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│    ┌─ PRIORITY 3: PV Shifting (deficit) ──────────────────┐    │
│    │  ELIF deficit > 0:                                   │    │
│    │    // Use only SOC ABOVE reserve                     │    │
│    │    energy_above_reserve = SOC[t] - pv_soc_min        │    │
│    │    IF energy_above_reserve > 0:                      │    │
│    │      discharge_pv[t] = min(deficit, available)       │    │
│    │    grid_import[t] = deficit - discharge_pv[t]        │    │
│    └───────────────────────────────────────────────────────┘    │
│                                                                 │
│  DEGRADATION METRICS:                                           │
│  ├── throughput_peak_mwh  ← Energy for peak shaving            │
│  ├── throughput_pv_mwh    ← Energy for PV shifting             │
│  ├── efc_peak             ← Cycles for peak shaving            │
│  ├── efc_pv               ← Cycles for PV shifting             │
│  ├── peak_events_count    ← Number of peak shaving events      │
│  └── charge_pv_pct        ← % of charging from PV vs grid      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.4 Mathematical Formulas

#### 10.4.1 Energy Balance

```
net_load(t) = load(t) - pv(t)

where:
  net_load(t) > 0  →  deficit (need energy from BESS/grid)
  net_load(t) < 0  →  PV surplus (can charge BESS)
  net_load(t) = 0  →  zero balance
```

#### 10.4.2 Charge/Discharge Efficiency

```
Roundtrip efficiency:    η_rt = η_charge × η_discharge

Typical for Li-ion:      η_rt = 0.90 (90%)
                         η_charge = √0.90 ≈ 0.9487 (94.87%)
                         η_discharge = √0.90 ≈ 0.9487 (94.87%)

Energy stored:           E_stored = E_input × η_charge
Energy delivered:        E_output = E_stored × η_discharge
Roundtrip losses:        E_loss = E_input × (1 - η_rt)
```

#### 10.4.3 State of Charge (SOC)

```
Charging:
  SOC(t+1) = SOC(t) + P_charge(t) × η_charge × Δt

Discharging:
  SOC(t+1) = SOC(t) - P_discharge(t) / η_discharge × Δt

Constraints:
  SOC_min × E_nom ≤ SOC(t) ≤ SOC_max × E_nom

Usable capacity:
  E_usable = E_nom × (SOC_max - SOC_min)
  E_usable = E_nom × (0.90 - 0.10) = 0.80 × E_nom
```

#### 10.4.4 Equivalent Full Cycles (EFC)

```
EFC = Σ discharge(t) / E_usable

Example:
  E_nom = 200 kWh
  E_usable = 200 × 0.80 = 160 kWh
  Annual discharge = 40,000 kWh
  EFC = 40,000 / 160 = 250 cycles/year
```

#### 10.4.5 NPV (Net Present Value)

```
NPV = Σ(t=1..n) [CF(t) / (1+r)^t] - CAPEX

where:
  CF(t) = annual_savings - annual_opex
  annual_savings = annual_discharge × energy_price
  annual_opex = CAPEX × opex_pct
  r = discount_rate (e.g., 0.07 = 7%)
  n = analysis_period (e.g., 25 years)

Alternative with PV factor:
  PV_factor = (1 - (1+r)^(-n)) / r
  NPV = CF × PV_factor - CAPEX
```

#### 10.4.6 Payback Period

```
Simple Payback = CAPEX / annual_net_savings

where:
  annual_net_savings = annual_savings × (1 - opex_pct)

Example:
  CAPEX = 330,000 PLN
  annual_savings = 50,000 PLN
  opex_pct = 1.5%
  annual_net_savings = 50,000 × 0.985 = 49,250 PLN
  Payback = 330,000 / 49,250 = 6.7 years
```

### 10.5 Input Parameters and Their Impact

| Parameter | Symbol | Impact on Result |
|-----------|--------|------------------|
| BESS Power | P_max | ↑ power → ↑ charge/discharge speed, ↑ cost |
| Capacity | E_nom | ↑ capacity → ↑ energy storage, ↑ cost |
| Duration (E/P) | D | ↑ duration → longer discharge, fewer cycles/day |
| SOC min/max | SOC_min, SOC_max | Narrower range → longer lifetime, less usable energy |
| Efficiency | η_rt | ↑ efficiency → less losses, higher savings |
| CAPEX/kWh | c_e | ↑ cost → longer payback, lower NPV |
| CAPEX/kW | c_p | ↑ cost → longer payback, lower NPV |
| Energy price | p_e | ↑ price → higher savings, better NPV |
| Discount rate | r | ↑ rate → lower NPV, shorter optimal horizon |

### 10.6 Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           BESS DATA FLOW                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  USER                                                                    │
│      │                                                                   │
│      ├─► Location (lat/lon) ────────────────────────────────────────┐    │
│      │                                                              │    │
│      ├─► Consumption profile (CSV) ─────────────────────────────┐   │    │
│      │                                                          │   │    │
│      └─► BESS parameters ───────────────────────────────────┐   │   │    │
│          (power, capacity, efficiency, prices)              │   │   │    │
│                                                             │   │   │    │
│                                                             ▼   ▼   ▼    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐  │
│  │   PVGIS     │    │   CSV/XLS   │    │      FRONTEND-BESS          │  │
│  │   API       │    │   Parser    │    │   (user parameters)         │  │
│  └──────┬──────┘    └──────┬──────┘    └──────────────┬──────────────┘  │
│         │                  │                          │                  │
│         ▼                  ▼                          ▼                  │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     PV-CALCULATION SERVICE                        │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Generate PV production profile (8760h)                    │  │   │
│  │  │  pv_generation[t] = pvlib.simulate(irradiance, temp, ...)  │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     BESS-OPTIMIZER SERVICE                        │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Grid Search: test combinations (power, energy)            │  │   │
│  │  │  For each: simulate dispatch → calculate NPV               │  │   │
│  │  │  Select configuration with highest NPV                     │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     BESS-DISPATCH SERVICE                         │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  Hourly simulation (8760 steps):                           │  │   │
│  │  │  - PV-Surplus: self-consumption                            │  │   │
│  │  │  - Peak Shaving: peak reduction                            │  │   │
│  │  │  - STACKED: combined services                              │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│                                  ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                          RESULTS                                  │   │
│  │  ├── Optimal power: 100 kW                                       │   │
│  │  ├── Optimal capacity: 200 kWh                                   │   │
│  │  ├── CAPEX: 330,000 PLN                                          │   │
│  │  ├── NPV (25 years): 450,000 PLN                                 │   │
│  │  ├── Payback: 6.7 years                                          │   │
│  │  ├── Annual cycles: 250                                          │   │
│  │  ├── Self-consumption: 85% → 95%                                 │   │
│  │  └── Profile SOC[8760], charge[8760], discharge[8760]            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

