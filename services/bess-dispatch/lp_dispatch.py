"""
PLIK: lp_dispatch.py
ROLA: LP solver — fizyka baterii (charge/discharge scheduling).
WEJŚCIE: BatteryParams, numpy arrays load_kw/pv_kw, PriceConfig, DispatchMode, buy/sell price overrides
WYJŚCIE: DispatchResult z hourly energy flows (charge/discharge/grid/soc), peak_reduction, degradation
NIE ROBI: Nie liczy oszczędności PLN (to robi build_savings_breakdown w sizing_runner),
          nie liczy NPV (to robi economics_engine), nie rozstrzyga cen (to robi price_resolver)

LP Dispatch Engine - Linear Programming with Rolling Horizon
=============================================================
Globally optimal BESS dispatch using scipy.optimize.linprog (HiGHS backend).

Ported from pagra-galileo ozetoolbox/solver with adaptations for
Energy Studio's async model (BatteryParams, DispatchResult, PriceConfig).

Formulation:
- Decision variables: SoC[0..n-1] (normalized 0-1), t_aux[0..n-1] (cost aux)
- Objective: minimize sum(t_aux) * capacity_kWh
- Power constraints: C-rate + connection limits via difference matrix
- Cost constraints: 4 piecewise-linear inequalities per timestep
- Mode constraints: zero-export (PV_SURPLUS), peak limit (PEAK_SHAVING)

Version: 1.4.0 (LP solver integration)
"""

import numpy as np
import logging
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from scipy.optimize import linprog, OptimizeResult

from models import (
    BatteryParams,
    DispatchResult,
    DispatchMode,
    DegradationMetrics,
    DegradationStatus,
    PriceConfig,
    LPSolverParams,
    EnergyFlows,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constraint Builders
# =============================================================================

def _build_difference_matrix(n: int, dt_hours: float) -> np.ndarray:
    """
    Build the SoC difference matrix (normalized by dt and capacity).

    SoC indexing convention:
      - Decision variable x[t] = SoC at END of timestep t (= beginning of t+1)
      - dSoC[t] = x[t] - x[t-1]   for t >= 1
      - dSoC[0] = x[0] - soc_init  (initial condition via b vector)
      - Power constraints and costs at timestep t use dSoC[t] and prices[t]

    Returns A_diff of shape (n, n) such that A_diff @ SoC = dSoC / dt
    (power in normalized units: fraction-of-capacity per hour, i.e. [1/h])
    """
    A = np.zeros((n, n))
    for t in range(n):
        A[t, t] = 1.0 / dt_hours
        if t > 0:
            A[t, t - 1] = -1.0 / dt_hours
    return A


def _build_power_constraints(
    n: int,
    dt_hours: float,
    soc_init: float,
    battery: BatteryParams,
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Build power rate constraints incorporating C-rate limits and mode-specific bounds.

    The normalized power = dSoC/dt is bounded by:
      lb_power <= dSoC/dt <= ub_power

    Bounds come from:
    - C-rate limits (battery power / capacity)
    - Peak shaving: grid_import <= peak_limit (with efficiency correction)

    PV_SURPLUS zero-export is NOT enforced here. It is handled by the cost
    function (sell_price ≈ 0 means no incentive to export), and any residual
    surplus beyond battery capacity becomes curtailment in post-processing.
    This avoids infeasibility when PV surplus > battery C-rate.

    Returns (A_power, b_power, n_rows)
    - 2*n inequality rows: upper bounds + lower bounds
    """
    cap = battery.energy_kwh
    c_rate = battery.power_kw / cap if cap > 0 else 0.0
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    # Base bounds: C-rate
    ub = np.full(n, c_rate)
    lb = np.full(n, -c_rate)

    # Peak shaving: tighten bounds to enforce grid_import <= peak_limit_kw
    #
    # Grid power = load - pv + P_batt_net
    # P_batt_net depends on direction (efficiency):
    #   Charging (dSoC > 0): P_batt_net = dSoC * cap / (eta_ch * dt)
    #   Discharging (dSoC < 0): P_batt_net = dSoC * cap * eta_dis / dt
    #
    # When load > pv + peak_limit (must discharge to meet peak):
    #   dSoC must be negative enough → tighten ub
    #   Required: (load - pv - peak_limit) / (cap * eta_dis) <= |dSoC/dt|
    #   → dSoC/dt <= -(load - pv - peak_limit) / (cap * eta_dis)
    #
    # When load < pv + peak_limit (headroom, can charge):
    #   Battery charging adds to grid import
    #   dSoC/dt <= (peak_limit - load + pv) * eta_ch / cap
    #   But only limit if this is < c_rate (don't over-constrain)
    if mode in (DispatchMode.PEAK_SHAVING, DispatchMode.STACKED) and peak_limit_kw is not None:
        headroom = peak_limit_kw - load_kw + pv_kw  # kW (positive = under limit)
        peak_ub = np.where(
            headroom >= 0,
            headroom * eta_ch / cap,        # Under peak: limit charge from grid
            headroom / (cap * eta_dis),     # Over peak: must discharge
        )
        # Only apply peak constraint where it's more restrictive than c_rate
        # AND where it still allows the LP to be feasible (ub >= lb)
        peak_ub_clipped = np.maximum(peak_ub, lb)  # Don't make ub < lb
        ub = np.minimum(ub, peak_ub_clipped)

    # Grid connection limit: battery charging from grid limited by available connection capacity
    # At each timestep: grid_import = load - pv + P_charge_from_grid
    # Total grid import cannot exceed grid_connection_kw
    # So P_charge_from_grid <= grid_connection_kw - (load - pv) when load > pv
    # In normalized units: dSoC/dt <= (grid_connection_kw - max(0, load - pv)) * eta_ch / cap
    if grid_connection_kw is not None and grid_connection_kw > 0:
        # Available grid capacity for battery charging (after serving load)
        net_load = load_kw - pv_kw  # Positive when load > PV (grid covers deficit)
        available_for_charge = grid_connection_kw - np.maximum(net_load, 0)
        # Only limit charging (positive dSoC), not discharging
        grid_ub = np.where(
            available_for_charge > 0,
            available_for_charge * eta_ch / cap,
            0.0  # No grid charging capacity available
        )
        grid_ub_clipped = np.maximum(grid_ub, lb)  # Feasibility
        ub = np.minimum(ub, grid_ub_clipped)

    # No-grid-charging constraint: battery may charge from PV only (not grid).
    # Battery can take ANY amount of PV (not just surplus over load).
    # Load imports cheap grid power when PV is diverted to battery.
    # dSoC/dt <= pv_kw * eta_ch / cap
    if not allow_grid_charging:
        nogrid_ub = pv_kw * eta_ch / cap
        nogrid_ub_clipped = np.maximum(nogrid_ub, lb)  # Feasibility
        ub = np.minimum(ub, nogrid_ub_clipped)

    # Build A_ub for power constraints
    A_diff = _build_difference_matrix(n, dt_hours)

    n_rows = 2 * n
    n_vars = 2 * n  # SoC + t_aux
    A_power = np.zeros((n_rows, n_vars))
    b_power = np.zeros(n_rows)

    # Row 0..n-1: A_diff @ SoC <= ub  →  dSoC/dt <= ub
    A_power[:n, :n] = A_diff
    b_power[:n] = ub
    # Fix first row for soc_init: dSoC[0] = (SoC[0] - soc_init) / dt
    b_power[0] = ub[0] + soc_init / dt_hours

    # Row n..2n-1: -A_diff @ SoC <= -lb  →  dSoC/dt >= lb
    A_power[n:, :n] = -A_diff
    b_power[n:] = -lb
    b_power[n] = -lb[0] - soc_init / dt_hours

    return A_power, b_power, n_rows


def _build_cost_constraints(
    n: int,
    dt_hours: float,
    soc_init: float,
    battery: BatteryParams,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Build piecewise-linear cost constraints.

    The cost at each timestep is modeled as:
      t_aux[t] >= cost_piece_j(dSoC[t])  for j = 0,1,2,3

    Four pieces capture all combinations of:
    - Charging vs discharging efficiency
    - Buy vs sell price

    This is the core of the LP formulation from Galileo.

    Piece formulas (in normalized units, all per-timestep):
      piece_0: t_aux >= dSoC * eta_ch * sell_price - norm_balance * dt * sell_price
      piece_1: t_aux >= dSoC / eta_dis * sell_price - norm_balance * dt * sell_price
      piece_2: t_aux >= dSoC * eta_ch * buy_price  - norm_balance * dt * buy_price
      piece_3: t_aux >= dSoC / eta_dis * buy_price  - norm_balance * dt * buy_price

    Returns (A_cost, b_cost, n_rows) with 4*n rows.
    """
    cap = battery.energy_kwh
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    # Normalized balance: (pv - load) / cap [fraction per timestep]
    net_kw = pv_kw - load_kw
    norm_balance = net_kw / cap  # fraction/timestep (power normalized)

    A_diff = _build_difference_matrix(n, dt_hours)

    n_rows = 4 * n
    n_vars = 2 * n  # SoC + t_aux
    A_cost = np.zeros((n_rows, n_vars))
    b_cost = np.zeros(n_rows)

    # For each piece j, the constraint is:
    # coeff_j * A_diff @ SoC - t_aux <= rhs_j
    # → coeff_j * dSoC/dt - t_aux <= rhs_j
    # Where we want t_aux >= coeff_j * dSoC/dt - rhs_j
    # Rewritten: coeff_j * A_diff @ SoC - I @ t_aux <= rhs_j

    eff_coeffs = [eta_ch, 1.0 / eta_dis, eta_ch, 1.0 / eta_dis]
    price_arrays = [sell_price, sell_price, buy_price, buy_price]

    for j in range(4):
        row_start = j * n
        eff = eff_coeffs[j]
        price = price_arrays[j]

        # SoC columns: eff * price[t] * A_diff
        for t in range(n):
            # Scale the difference matrix row by eff * price[t]
            A_cost[row_start + t, :n] = eff * price[t] * A_diff[t, :]

        # t_aux columns: -I (we want t_aux >= piece)
        for t in range(n):
            A_cost[row_start + t, n + t] = -1.0

        # RHS: norm_balance * dt * price (the baseline cost without battery)
        for t in range(n):
            b_cost[row_start + t] = norm_balance[t] * dt_hours * price[t]

    # Fix soc_init in first timestep of each piece
    for j in range(4):
        eff = eff_coeffs[j]
        price = price_arrays[j]
        row = j * n
        # The A_diff[0] row uses SoC[0] - soc_init, so adjust b
        b_cost[row] += eff * price[0] * soc_init / dt_hours

    return A_cost, b_cost, n_rows


def _build_mode_constraints(
    n: int,
    dt_hours: float,
    soc_init: float,
    battery: BatteryParams,
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Build mode-specific constraints (additional rows beyond power bounds).

    Currently no extra constraint rows are needed because:

    PV_SURPLUS (zero-export):
      Handled by the cost function (sell_price ≈ 0 means no incentive to export).
      Surplus beyond battery capacity becomes curtailment in post-processing.
      A hard zero-export constraint would be infeasible when surplus > C-rate.

    PEAK_SHAVING:
      Handled by tightened power bounds in _build_power_constraints with
      efficiency correction. This is more precise than separate constraint rows.

    STACKED:
      Combines both approaches above.

    Returns (A_mode, b_mode, n_rows) - currently always empty (0 rows).
    """
    n_vars = 2 * n
    return np.zeros((0, n_vars)), np.zeros(0), 0


# =============================================================================
# Single Window LP Solver
# =============================================================================

def _try_solve_lp_core(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    soc_init: float,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    time_limit: float = 30.0,
    soc_min_override: Optional[float] = None,
    soc_max_override: Optional[float] = None,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> Optional[np.ndarray]:
    """
    Core LP solver — single attempt with given parameters.

    Returns SoC trajectory (normalized 0-1) of length n, or None if infeasible.
    """
    n = len(pv_kw)
    cap = battery.energy_kwh
    n_vars = 2 * n

    if cap <= 0 or n == 0:
        return None

    c = np.zeros(n_vars)
    c[n:] = cap

    A_power, b_power, _ = _build_power_constraints(
        n, dt_hours, soc_init, battery, pv_kw, load_kw, mode, peak_limit_kw,
        grid_connection_kw=grid_connection_kw,
        allow_grid_charging=allow_grid_charging,
    )
    A_cost, b_cost, _ = _build_cost_constraints(
        n, dt_hours, soc_init, battery, buy_price, sell_price, pv_kw, load_kw
    )
    A_mode, b_mode, n_mode = _build_mode_constraints(
        n, dt_hours, soc_init, battery, pv_kw, load_kw, mode, peak_limit_kw
    )

    if n_mode > 0:
        A_ub = np.vstack([A_power, A_cost, A_mode])
        b_ub = np.concatenate([b_power, b_cost, b_mode])
    else:
        A_ub = np.vstack([A_power, A_cost])
        b_ub = np.concatenate([b_power, b_cost])

    soc_lo = soc_min_override if soc_min_override is not None else battery.soc_min
    soc_hi = soc_max_override if soc_max_override is not None else battery.soc_max
    bounds = [(soc_lo, soc_hi) for _ in range(n)] + [(None, None) for _ in range(n)]

    try:
        result: OptimizeResult = linprog(
            c=c, A_ub=A_ub, b_ub=b_ub, bounds=bounds,
            method='highs',
            options={'disp': False, 'time_limit': time_limit},
        )
    except Exception as e:
        logger.warning(f"LP solver exception: {e}")
        return None

    if result.success:
        return result.x[:n]
    return None


def solve_lp_window(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    soc_init: float,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    time_limit: float = 30.0,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> Optional[np.ndarray]:
    """
    Solve LP for a single time window with progressive constraint relaxation.

    Tries up to 4 relaxation levels to avoid infeasibility:
      0. Original constraints
      1. Relaxed peak limit (+50% headroom)
      2. No peak limit constraint
      3. No peak limit + full SoC range (0-1)

    Returns SoC trajectory of length n, or None only if all levels fail.
    """
    n = len(pv_kw)
    if battery.energy_kwh <= 0 or n == 0:
        return None

    # Level 0: original constraints
    result = _try_solve_lp_core(
        pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
        soc_init, mode, peak_limit_kw, time_limit,
        grid_connection_kw=grid_connection_kw,
        allow_grid_charging=allow_grid_charging,
    )
    if result is not None:
        return result

    # Level 1: relaxed peak limit (+50%)
    if peak_limit_kw is not None:
        result = _try_solve_lp_core(
            pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
            soc_init, mode, peak_limit_kw * 1.5, time_limit,
            grid_connection_kw=grid_connection_kw,
            allow_grid_charging=allow_grid_charging,
        )
        if result is not None:
            logger.info(f"LP window solved with relaxed peak limit (x1.5)")
            return result

    # Level 2: no peak limit
    if peak_limit_kw is not None:
        result = _try_solve_lp_core(
            pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
            soc_init, mode, None, time_limit,
            grid_connection_kw=grid_connection_kw,
            allow_grid_charging=allow_grid_charging,
        )
        if result is not None:
            logger.info(f"LP window solved without peak limit constraint")
            return result

    # Level 3: no peak limit + full SoC range + no grid limit + allow grid charging
    result = _try_solve_lp_core(
        pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
        soc_init, mode, None, time_limit,
        soc_min_override=0.0, soc_max_override=1.0,
        grid_connection_kw=None,  # Drop grid limit as last resort
    )
    if result is not None:
        logger.info(f"LP window solved with relaxed SoC bounds + no peak/grid limit")
        return result

    return None


# =============================================================================
# Rolling Horizon Orchestrator
# =============================================================================

def lp_dispatch_rolling(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    lp_config: Optional[LPSolverParams] = None,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> np.ndarray:
    """
    Rolling horizon LP dispatch (v7.0.0: always succeeds).

    Splits the full horizon into overlapping windows:
    - forecast_steps: how far ahead the LP looks
    - keep_steps: how many steps we keep from each solve

    This gives near-global optimality while keeping LP size manageable.

    Returns:
        Full SoC trajectory (normalized 0-1) of length n_total.
        Always succeeds — infeasible windows use hold-SoC fallback.
    """
    config = lp_config or LPSolverParams()
    n_total = len(pv_kw)

    forecast_steps = int(config.forecast_hours / dt_hours)
    keep_steps = int(config.keep_hours / dt_hours)

    # Ensure keep <= forecast
    keep_steps = min(keep_steps, forecast_steps)

    soc_full = np.zeros(n_total)
    soc_init = battery.soc_initial
    cursor = 0

    while cursor < n_total:
        # Window boundaries
        window_end = min(cursor + forecast_steps, n_total)
        window_size = window_end - cursor

        # Slice data for this window
        pv_win = pv_kw[cursor:window_end]
        load_win = load_kw[cursor:window_end]
        buy_win = buy_price[cursor:window_end]
        sell_win = sell_price[cursor:window_end]

        # Solve LP for this window
        soc_win = solve_lp_window(
            pv_kw=pv_win,
            load_kw=load_win,
            battery=battery,
            dt_hours=dt_hours,
            buy_price=buy_win,
            sell_price=sell_win,
            soc_init=soc_init,
            mode=mode,
            peak_limit_kw=peak_limit_kw,
            time_limit=config.time_limit_seconds,
            grid_connection_kw=grid_connection_kw,
            allow_grid_charging=allow_grid_charging,
        )

        if soc_win is None:
            # All relaxation levels exhausted — hold SoC (battery idle)
            logger.warning(
                f"LP window infeasible at cursor={cursor} (all relaxation levels), "
                f"holding SoC at {soc_init:.3f} for {window_size} steps"
            )
            actual_keep = min(keep_steps, window_size)
            soc_full[cursor:cursor + actual_keep] = soc_init
            cursor += actual_keep
            continue

        # Keep results
        actual_keep = min(keep_steps, window_size)
        soc_full[cursor:cursor + actual_keep] = soc_win[:actual_keep]

        # Update soc_init for next window
        soc_init = soc_win[actual_keep - 1]

        cursor += actual_keep

    return soc_full


# =============================================================================
# Post-processing: SoC trajectory → dispatch arrays
# =============================================================================

def _soc_to_power_arrays(
    soc: np.ndarray,
    soc_init: float,
    battery: BatteryParams,
    dt_hours: float,
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    mode: DispatchMode = DispatchMode.PV_SURPLUS,
) -> dict:
    """
    Convert SoC trajectory (normalized) to physical power/energy arrays.

    Returns dict with:
        charge, discharge, grid_import, grid_export, direct_pv,
        curtailment, soc_kwh, soc_pct
    """
    n = len(soc)
    cap = battery.energy_kwh
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    # Build full SoC series with initial value
    soc_full = np.zeros(n + 1)
    soc_full[0] = soc_init
    soc_full[1:] = soc

    # dSoC (normalized, positive = charging)
    dsoc = np.diff(soc_full)  # length n

    # Battery power at terminals (kW, positive = charging, negative = discharging)
    # When charging (dsoc > 0): P_charge_kW = dsoc * cap / dt / eta_ch
    #   (we need more power from grid/PV than what's stored, due to losses)
    #   Wait - convention: dsoc * cap / dt = energy stored per hour
    #   Power INTO battery = dsoc * cap / dt_hours
    #   Power FROM SOURCE = (dsoc * cap / dt_hours) / eta_ch
    #   Actually let me think carefully:
    #   Energy stored in battery = dsoc * cap (kWh per step)
    #   Energy consumed from source = dsoc * cap / eta_ch
    #   Power from source (charge power at terminals) = dsoc * cap / (eta_ch * dt_hours)

    # When discharging (dsoc < 0):
    #   Energy removed from battery = |dsoc| * cap (kWh per step)
    #   Energy delivered to load = |dsoc| * cap * eta_dis
    #   Power delivered (discharge power at terminals) = |dsoc| * cap * eta_dis / dt_hours

    charge_kw = np.zeros(n)
    discharge_kw = np.zeros(n)

    charging_mask = dsoc > 0
    discharging_mask = dsoc < 0

    # Charge power (kW at battery terminals, from PV/grid perspective)
    charge_kw[charging_mask] = dsoc[charging_mask] * cap / (eta_ch * dt_hours)

    # Discharge power (kW delivered to load)
    discharge_kw[discharging_mask] = -dsoc[discharging_mask] * cap * eta_dis / dt_hours

    # Grid power = load - pv - discharge + charge
    # (positive = import from grid, negative = export to grid)
    grid_power = load_kw - pv_kw + charge_kw - discharge_kw

    grid_import = np.maximum(grid_power, 0.0)
    grid_export = np.maximum(-grid_power, 0.0)

    # Direct PV consumption = min(pv, load)
    direct_pv = np.minimum(pv_kw, load_kw)

    # Curtailment: PV that's neither consumed directly, nor charges battery, nor exported
    pv_used = direct_pv + charge_kw + grid_export  # total PV utilized
    # Actually: PV goes to: direct_pv, charge, export. Curtailment = pv - (direct + charge_from_pv + export)
    # But charge might come from grid too. In PV_SURPLUS, charge comes from PV surplus.
    # For LP general case: curtailment = max(pv - load - charge_kw, 0) when grid_export = 0
    # In zero-export mode: curtailment = pv - load - charge_kw when pv > load
    # General: curtailment = max(pv - load - charge_kw + discharge_kw, 0) - grid_export
    # Simplification: curtailment = max(pv - load - charge_kw + discharge_kw + grid_export, 0)
    # Actually: energy balance: pv + grid_import + discharge = load + charge + grid_export + curtailment
    # → curtailment = pv + grid_import + discharge - load - charge - grid_export
    # But grid_import - grid_export = grid_power = load - pv + charge - discharge
    # → curtailment = pv + (load - pv + charge - discharge) + discharge - load - charge - 0
    # → curtailment = 0 ... that's not right.

    # The issue: in LP zero-export mode, excess PV beyond battery capacity IS curtailed.
    # The LP models this by not requiring all surplus to be absorbed (infeasible if surplus > c_rate).
    # Curtailment in LP = PV surplus that the battery couldn't absorb.

    # Better: from energy balance per step:
    # pv[t] = direct_pv[t] + charge_from_pv[t] + export[t] + curtailment[t]
    # load[t] = direct_pv[t] + discharge[t] + grid_import[t]
    # In zero-export: export = 0

    # Curtailment calculation:
    # In PV_SURPLUS mode, any grid export is physically curtailment
    # (zero-export constraint not enforced in LP to avoid infeasibility).
    # Convert export to curtailment in post-processing.
    if mode in (DispatchMode.PV_SURPLUS, DispatchMode.STACKED):
        curtailment = grid_export.copy()
        grid_export = np.zeros(n)
    else:
        # For PEAK_SHAVING/ARBITRAGE: curtailment = PV surplus not used
        surplus = np.maximum(pv_kw - load_kw, 0.0)
        curtailment = np.maximum(surplus - charge_kw - grid_export, 0.0)

    # SOC in kWh and %
    soc_kwh = soc_full[:-1] * cap  # length n
    soc_pct = soc_full[:-1] * 100.0

    return {
        'charge_kw': charge_kw,
        'discharge_kw': discharge_kw,
        'grid_import_kw': grid_import,
        'grid_export_kw': grid_export,
        'direct_pv_kw': direct_pv,
        'curtailment_kw': curtailment,
        'soc_kwh': soc_kwh,
        'soc_pct': soc_pct,
        'soc_full': soc_full,
    }


# =============================================================================
# Price Resolution Helper
# =============================================================================

def resolve_price_arrays(
    prices: Optional[PriceConfig],
    n_steps: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert PriceConfig to buy/sell price arrays [PLN/kWh].

    For flat pricing: constant arrays.
    For ToU pricing: would use zone-based rates (future extension).

    Returns (buy_price, sell_price) arrays of length n_steps.
    """
    if prices is None:
        prices = PriceConfig()

    buy_price = np.full(n_steps, prices.import_price_pln_mwh / 1000.0)  # PLN/kWh
    sell_price = np.full(n_steps, prices.export_price_pln_mwh / 1000.0)  # PLN/kWh

    # Ensure sell_price is at least a small positive value for LP stability
    sell_price = np.maximum(sell_price, 1e-6)

    return buy_price, sell_price


def resolve_buy_sell_for_dispatch(
    prices: Optional[PriceConfig],
    n_steps: int,
    import_prices: Optional[np.ndarray] = None,
    export_prices: Optional[np.ndarray] = None,
    arbitrage_config: Optional[Any] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Unified buy/sell price resolution for both dispatch and sizing.

    Price semantics for RDN arbitrage:
    - buy_price (import) = all-in cost: RDN + distribution + fees + capacity fee.
      This is what you pay when buying energy from the grid.
    - sell_price (export) = raw RDN price (prosumer export price, no OSD fees).
      This is what you receive when selling PV surplus to the grid.

    The spread (buy - sell ≈ OSD fees) drives arbitrage value:
    storing PV costs you the lost export revenue (raw RDN),
    but discharging later saves the full all-in import price.

    Args:
        prices: PriceConfig with import/export prices
        n_steps: number of timesteps
        import_prices: per-timestep buy prices [PLN/kWh] (all-in: RDN + OSD fees)
        export_prices: per-timestep sell prices [PLN/kWh] (raw RDN, prosumer sell)
        arbitrage_config: optional ArbitrageConfig (needs .enabled attribute)

    Returns:
        (buy_price_arr, sell_price_arr) both [PLN/kWh] × n_steps
    """
    buy_arr = import_prices
    sell_arr = None

    if buy_arr is None:
        buy_arr, sell_arr = resolve_price_arrays(prices, n_steps)
    else:
        _, sell_arr = resolve_price_arrays(prices, n_steps)
        if arbitrage_config and getattr(arbitrage_config, 'enabled', False):
            if export_prices is not None and len(export_prices) >= n_steps:
                # Explicit export prices: raw RDN (prosumer sell price without OSD)
                sell_arr = export_prices[:n_steps]
            elif prices and prices.export_price_pln_mwh <= 0.01:
                # Fallback: buy_price * 0.95 as opportunity-cost proxy
                sell_arr = buy_arr * 0.95

    return buy_arr, sell_arr


# =============================================================================
# Public Entry Point
# =============================================================================

def dispatch_lp(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    prices: Optional[PriceConfig] = None,
    mode: DispatchMode = DispatchMode.PV_SURPLUS,
    peak_limit_kw: Optional[float] = None,
    lp_config: Optional[LPSolverParams] = None,
    return_hourly: bool = True,
    buy_price_override: Optional[np.ndarray] = None,
    sell_price_override: Optional[np.ndarray] = None,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> DispatchResult:
    """
    Main LP dispatch entry point (v7.0.0: self-sufficient, never returns None).

    Runs rolling-horizon LP optimization with progressive constraint relaxation.
    Always produces a valid DispatchResult — infeasible windows use hold-SoC fallback.

    Parameters:
    -----------
    pv_kw : array
        PV generation [kW] per timestep
    load_kw : array
        Load consumption [kW] per timestep
    battery : BatteryParams
        Battery parameters
    dt_hours : float
        Timestep duration [hours]
    prices : PriceConfig
        Energy prices
    mode : DispatchMode
        Dispatch mode (PV_SURPLUS, PEAK_SHAVING, STACKED)
    peak_limit_kw : float, optional
        Grid import limit for peak shaving
    lp_config : LPSolverParams, optional
        LP solver configuration
    return_hourly : bool
        Include hourly arrays in result
    buy_price_override : array, optional
        Time-varying buy prices [PLN/kWh] (overrides PriceConfig)
    sell_price_override : array, optional
        Time-varying sell prices [PLN/kWh] (overrides PriceConfig)

    Returns:
    --------
    DispatchResult or None if LP fails
    """
    from dispatch_engine import (
        calculate_degradation_metrics,
        calculate_degradation_metrics_stacked,
        create_savings_breakdown,
        create_prices_summary,
        calculate_energy_cost,
    )
    from energy_flows_helper import create_energy_flows

    n = len(pv_kw)
    prices = prices or PriceConfig()

    # Resolve price arrays
    if buy_price_override is not None and sell_price_override is not None:
        buy_price = buy_price_override
        sell_price = sell_price_override
    else:
        buy_price, sell_price = resolve_price_arrays(prices, n)

    # Run rolling horizon LP
    soc_trajectory = lp_dispatch_rolling(
        pv_kw=pv_kw,
        load_kw=load_kw,
        battery=battery,
        dt_hours=dt_hours,
        buy_price=buy_price,
        sell_price=sell_price,
        mode=mode,
        peak_limit_kw=peak_limit_kw,
        lp_config=lp_config,
        grid_connection_kw=grid_connection_kw,
        allow_grid_charging=allow_grid_charging,
    )

    # Post-process: SoC → power arrays
    arrays = _soc_to_power_arrays(
        soc=soc_trajectory,
        soc_init=battery.soc_initial,
        battery=battery,
        dt_hours=dt_hours,
        pv_kw=pv_kw,
        load_kw=load_kw,
        mode=mode,
    )

    charge = arrays['charge_kw']
    discharge = arrays['discharge_kw']
    grid_import = arrays['grid_import_kw']
    grid_export = arrays['grid_export_kw']
    direct_pv = arrays['direct_pv_kw']
    curtailment = arrays['curtailment_kw']
    soc = arrays['soc_full']  # length n+1

    # Calculate totals
    total_pv = float(np.sum(pv_kw) * dt_hours)
    total_load = float(np.sum(load_kw) * dt_hours)
    total_direct = float(np.sum(direct_pv) * dt_hours)
    total_charge = float(np.sum(charge) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)
    total_export = float(np.sum(grid_export) * dt_hours)
    total_curtail = float(np.sum(curtailment) * dt_hours)

    # Self-consumption
    self_consumption = total_direct + total_discharge
    self_consumption_pct = (self_consumption / total_pv * 100) if total_pv > 0 else 0.0
    grid_independence = ((total_load - total_import) / total_load * 100) if total_load > 0 else 0.0

    # --- Classify discharge: peak shaving vs PV surplus ---
    # Peak shaving discharge = when load exceeds PV + peak_limit (battery MUST discharge to meet peak constraint)
    # PV surplus discharge = all other discharge (energy optimization, self-consumption)
    if mode in (DispatchMode.STACKED, DispatchMode.PEAK_SHAVING) and peak_limit_kw is not None:
        net_load = load_kw - pv_kw  # net load (positive = needs grid/battery)
        peak_excess = np.maximum(net_load - peak_limit_kw, 0.0)  # kW over limit
        # Peak shaving discharge: min(actual discharge, what's needed for peak shaving)
        discharge_peak_kw = np.minimum(discharge, peak_excess)
        discharge_pv_kw = discharge - discharge_peak_kw
        discharge_peak_kwh = float(np.sum(discharge_peak_kw) * dt_hours)
        discharge_pv_kwh = float(np.sum(discharge_pv_kw) * dt_hours)
        peak_events = int(np.sum(discharge_peak_kw > 0.1))
        peak_max_dis_kw = float(np.max(discharge_peak_kw)) if peak_events > 0 else 0.0
    else:
        discharge_peak_kwh = 0.0
        discharge_pv_kwh = total_discharge
        peak_events = 0
        peak_max_dis_kw = 0.0

    # Degradation - use stacked version for STACKED mode
    # charge_from_pv = min(charge, pv) — battery can take any PV, not just surplus
    charge_from_pv_deg = np.minimum(charge, pv_kw)
    charge_from_grid_deg = np.maximum(charge - charge_from_pv_deg, 0.0)
    charge_from_pv_kwh = float(np.sum(charge_from_pv_deg) * dt_hours)
    charge_from_grid_kwh = float(np.sum(charge_from_grid_deg) * dt_hours)

    if mode in (DispatchMode.STACKED, DispatchMode.PEAK_SHAVING):
        degradation = calculate_degradation_metrics_stacked(
            total_charge=total_charge,
            total_discharge=total_discharge,
            discharge_peak=discharge_peak_kwh,
            discharge_pv=discharge_pv_kwh,
            battery=battery,
            total_hours=n * dt_hours,
            peak_events_count=peak_events,
            peak_max_discharge_kw=peak_max_dis_kw,
            charge_from_pv_kwh=charge_from_pv_kwh,
            charge_from_grid_kwh=charge_from_grid_kwh,
            discharge_hourly=discharge,
            dt_hours=dt_hours,
        )
    else:
        degradation = calculate_degradation_metrics(
            total_charge, total_discharge, battery, n * dt_hours
        )

    # Economics
    import_price_scalar = prices.import_price_pln_mwh / 1000.0
    export_price_scalar = prices.export_price_pln_mwh / 1000.0

    # Baseline: no battery
    baseline_import = np.maximum(load_kw - pv_kw, 0)
    baseline_export = np.maximum(pv_kw - load_kw, 0)

    baseline_cost = calculate_energy_cost(baseline_import, buy_price, dt_hours) \
                    - calculate_energy_cost(baseline_export, sell_price, dt_hours)
    project_cost = calculate_energy_cost(grid_import, buy_price, dt_hours) \
                   - calculate_energy_cost(grid_export, sell_price, dt_hours)

    # --- Split savings: energy vs peak shaving vs arbitrage ---
    # Total savings from LP optimization
    total_savings_pln = baseline_cost - project_cost

    # Peak shaving savings (demand charge reduction) — only for modes that explicitly do peak shaving
    baseline_peak = float(np.max(baseline_import))
    project_peak = float(np.max(grid_import))
    if mode in (DispatchMode.STACKED, DispatchMode.PEAK_SHAVING, DispatchMode.LOAD_ONLY):
        demand_charge_rate_annual = prices.annual_demand_charge_pln_kw
        demand_charge_savings_pln = (baseline_peak - project_peak) * demand_charge_rate_annual
    else:
        demand_charge_savings_pln = 0.0

    # Arbitrage timing value: measures how well the LP times charge/discharge
    # vs flat-average pricing. This is a DIAGNOSTIC metric (dispatch quality),
    # distinct from the ECONOMIC arbitrage_savings in sizing_runner.py which
    # computes actual grid_charge_cost vs discharge_value.
    price_spread = buy_price - sell_price
    has_price_variation = float(np.std(buy_price)) > 1e-6
    if has_price_variation:
        avg_buy = float(np.mean(buy_price))
        discharge_energy = discharge * dt_hours
        total_dis_energy = np.sum(discharge_energy)
        if total_dis_energy > 0:
            weighted_buy_at_discharge = float(np.sum(buy_price * discharge_energy)) / total_dis_energy
            arbitrage_timing_value_pln = (weighted_buy_at_discharge - avg_buy) * total_dis_energy
            arbitrage_timing_value_pln = max(arbitrage_timing_value_pln, 0.0)
        else:
            arbitrage_timing_value_pln = 0.0
    else:
        arbitrage_timing_value_pln = 0.0
    # For SavingsBreakdown backward compat — arbitrage_savings_pln is DEPRECATED (2026-03-11).
    # Canonical metric is arbitrage_timing_value_pln (discharge-weighted price vs avg buy).
    arbitrage_savings_pln = arbitrage_timing_value_pln  # deprecated alias

    # Energy savings = total savings minus demand charge and arbitrage
    energy_savings_pln = total_savings_pln - demand_charge_savings_pln - arbitrage_savings_pln
    # Ensure non-negative (rounding)
    energy_savings_pln = max(energy_savings_pln, 0.0)

    # Degradation cost — intentionally POST-DISPATCH accounting, not in LP objective.
    # LP minimizes import cost only; degradation enters NPV/economics layer via SavingsBreakdown.
    # Rationale: including degradation in LP would require nonlinear cycling penalty → intractable.
    degradation_cost_pln = degradation.throughput_total_mwh * 30.0  # ~30 PLN/MWh throughput cost

    # annual_savings for NPV: energy + demand_charge + arbitrage (total_savings already includes energy part)
    annual_savings = energy_savings_pln + demand_charge_savings_pln + arbitrage_savings_pln

    savings_breakdown = create_savings_breakdown(
        energy_savings_pln=energy_savings_pln,
        demand_charge_savings_pln=demand_charge_savings_pln,
        arbitrage_savings_pln=arbitrage_savings_pln,
        capacity_fee_savings_pln=0.0,
        degradation_cost_pln=degradation_cost_pln,
    )

    prices_summary = create_prices_summary(prices, tariff_type="flat")

    info_dict = {
        "solver": "lp",
        "lp_config": {
            "forecast_hours": (lp_config or LPSolverParams()).forecast_hours,
            "keep_hours": (lp_config or LPSolverParams()).keep_hours,
        },
    }

    # RDN arbitrage metrics (when time-varying prices are used)
    if has_price_variation:
        charge_energy = charge * dt_hours
        total_chg_energy = float(np.sum(charge_energy))
        total_dis_energy_m = float(np.sum(discharge * dt_hours))
        avg_charge_price = float(np.sum(buy_price * charge_energy) / total_chg_energy) if total_chg_energy > 0 else 0.0
        avg_discharge_price = float(np.sum(buy_price * discharge * dt_hours) / total_dis_energy_m) if total_dis_energy_m > 0 else 0.0
        info_dict["rdn_arbitrage_metrics"] = {
            "avg_charge_price_pln_mwh": round(avg_charge_price * 1000, 2),
            "avg_discharge_price_pln_mwh": round(avg_discharge_price * 1000, 2),
            "price_spread_pln_mwh": round((avg_discharge_price - avg_charge_price) * 1000, 2),
            "total_charge_kwh": round(total_chg_energy, 1),
            "total_discharge_kwh": round(total_dis_energy_m, 1),
            # Diagnostic: timing quality metric (discharge at high price vs avg)
            "arbitrage_timing_value_pln": round(arbitrage_timing_value_pln, 2),
            # DEPRECATED (2026-03-11): use arbitrage_timing_value_pln instead
            "arbitrage_savings_pln": round(arbitrage_savings_pln, 2),  # backward compat
            "price_min_pln_mwh": round(float(np.min(buy_price)) * 1000, 2),
            "price_max_pln_mwh": round(float(np.max(buy_price)) * 1000, 2),
            "price_avg_pln_mwh": round(float(np.mean(buy_price)) * 1000, 2),
        }

    # Determine mode for result
    result_mode = mode
    if mode == DispatchMode.STACKED:
        result_mode = DispatchMode.STACKED
    elif mode == DispatchMode.PEAK_SHAVING:
        result_mode = DispatchMode.PEAK_SHAVING
    else:
        result_mode = DispatchMode.PV_SURPLUS

    result = DispatchResult(
        mode=result_mode,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=total_pv,
        total_load_kwh=total_load,
        total_direct_pv_kwh=total_direct,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_curtailment_kwh=total_curtail,
        self_consumption_kwh=self_consumption,
        self_consumption_pct=self_consumption_pct,
        grid_independence_pct=grid_independence,
        original_peak_kw=baseline_peak,
        new_peak_kw=project_peak,
        peak_reduction_kw=baseline_peak - project_peak,
        peak_reduction_pct=((baseline_peak - project_peak) / baseline_peak * 100)
                          if baseline_peak > 0 else 0.0,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        savings_breakdown=savings_breakdown,
        prices_summary=prices_summary,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] * 100.0).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    # Compute charge_from_grid (shared by battery_trace and hourly profiles)
    # charge_from_pv = min(charge, pv) — battery can take any PV, not just surplus
    charge_from_pv_bt = np.minimum(charge, pv_kw)
    charge_from_grid_bt = np.maximum(charge - charge_from_pv_bt, 0.0)

    # Always populate charge_from_grid for K-class capacity fee calculations
    result.hourly_charge_from_grid_kw = charge_from_grid_bt.tolist()

    # Battery trace (v2.2.0) - always generate for sizing (SOC histogram needs it)
    from battery_trace_helper import create_battery_trace_from_dispatch_result
    discharge_to_load_bt = discharge.copy()
    discharge_to_grid_bt = np.zeros(n)
    result.battery_trace = create_battery_trace_from_dispatch_result(
        soc_array=soc * battery.energy_kwh,
        charge_array=charge,
        discharge_array=discharge,
        charge_from_pv_array=charge_from_pv_bt,
        charge_from_grid_array=charge_from_grid_bt,
        discharge_to_load_array=discharge_to_load_bt,
        discharge_to_grid_array=discharge_to_grid_bt,
        interval_minutes=int(dt_hours * 60),
        battery_energy_kwh=battery.energy_kwh,
        battery_power_kw=battery.power_kw,
    )

    # Energy flows
    pv_to_load_kwh_arr = direct_pv * dt_hours
    # Charge from PV: min(charge, pv) — battery can take any PV, not just surplus
    charge_from_pv = np.minimum(charge, pv_kw)
    charge_from_grid = np.maximum(charge - charge_from_pv, 0.0)

    pv_to_batt_kwh_arr = charge_from_pv * dt_hours
    pv_curtail_kwh_arr = curtailment * dt_hours
    batt_to_load_kwh_arr = discharge * dt_hours
    batt_charge_grid_kwh_arr = charge_from_grid * dt_hours
    grid_import_kwh_arr = grid_import * dt_hours
    grid_export_kwh_arr = grid_export * dt_hours
    soc_kwh_arr = soc[:-1] * battery.energy_kwh

    # Battery losses
    total_energy_in = np.sum(charge * dt_hours)
    total_energy_out = np.sum(discharge * dt_hours)
    total_loss = total_energy_in - total_energy_out + (soc[0] - soc[-1]) * battery.energy_kwh
    throughput_per_step = charge + discharge
    total_throughput = np.sum(throughput_per_step)
    if total_throughput > 0 and total_loss > 0:
        batt_losses_kwh_arr = throughput_per_step / total_throughput * total_loss
    else:
        batt_losses_kwh_arr = np.zeros(n)

    result.energy_flows = create_energy_flows(
        grid_import_kwh=grid_import_kwh_arr,
        grid_export_kwh=grid_export_kwh_arr,
        pv_to_load_kwh=pv_to_load_kwh_arr,
        pv_to_batt_kwh=pv_to_batt_kwh_arr,
        pv_curtail_kwh=pv_curtail_kwh_arr,
        batt_to_load_kwh=batt_to_load_kwh_arr,
        batt_charge_from_grid_kwh=batt_charge_grid_kwh_arr,
        batt_losses_kwh=batt_losses_kwh_arr,
        soc_kwh=soc_kwh_arr,
        include_timeseries=False,
    )

    return result


# =============================================================================
# Capacity Fee Multi-Solve (Flatness Constraint)
# =============================================================================

def dispatch_lp_with_capacity_optimization(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    prices: Optional[PriceConfig] = None,
    mode: DispatchMode = DispatchMode.PV_SURPLUS,
    peak_limit_kw: Optional[float] = None,
    lp_config: Optional[LPSolverParams] = None,
    return_hourly: bool = True,
    buy_price_override: Optional[np.ndarray] = None,
    sell_price_override: Optional[np.ndarray] = None,
    time_index: Optional[List[datetime]] = None,
    capacity_fee_config: Optional[Any] = None,
    premium_levels: Optional[List[float]] = None,
    grid_connection_kw: Optional[float] = None,
    allow_grid_charging: bool = True,
) -> Tuple['DispatchResult', Optional[Dict[str, Any]]]:
    """
    Multi-solve LP dispatch with capacity fee (opłata mocowa) optimization.

    Inspired by pagra-galileo's flatness constraint approach:
    instead of adding hard constraints (infeasible in rolling horizon),
    we internalize the capacity fee into the price signal by adding
    premiums to buy_price during selected hours.

    Each premium level incentivizes the LP to shape grid demand differently.
    The run with lowest total cost (energy + capacity fee) wins.

    Returns:
        Tuple of (best_dispatch_result, capacity_fee_info_dict)
    """
    from capacity_fee_pl.calculator import (
        compute_capacity_fee,
        build_selected_hours_mask,
    )
    from capacity_fee_pl.models import CapacityFeeConfig

    n = len(pv_kw)

    if capacity_fee_config is None:
        capacity_fee_config = CapacityFeeConfig()

    if time_index is None or len(time_index) != n:
        logger.warning("No time_index for cap-fee optimization, falling back to standard dispatch")
        result = dispatch_lp(
            pv_kw, load_kw, battery, dt_hours, prices, mode,
            peak_limit_kw, lp_config, return_hourly,
            buy_price_override, sell_price_override,
            grid_connection_kw=grid_connection_kw,
            allow_grid_charging=allow_grid_charging,
        )
        return result, None

    selected_mask = build_selected_hours_mask(time_index, capacity_fee_config)
    som = capacity_fee_config.som_pln_per_kwh

    if buy_price_override is not None and sell_price_override is not None:
        base_buy = buy_price_override.copy()
        base_sell = sell_price_override.copy()
    else:
        base_buy, base_sell = resolve_price_arrays(prices, n)

    if premium_levels is None:
        premium_levels = [
            0.0,
            som * 0.25,
            som * 0.50,
            som * 0.83,
            som * 1.20,
        ]

    best_result = None
    best_total_cost = float('inf')
    best_cap_fee_info = None
    best_premium = 0.0
    all_attempts = []

    for premium in premium_levels:
        modified_buy = base_buy.copy()
        modified_buy[selected_mask] += premium

        result = dispatch_lp(
            pv_kw=pv_kw, load_kw=load_kw, battery=battery,
            dt_hours=dt_hours, prices=prices, mode=mode,
            peak_limit_kw=peak_limit_kw, lp_config=lp_config,
            return_hourly=True,
            buy_price_override=modified_buy,
            sell_price_override=base_sell,
            grid_connection_kw=grid_connection_kw,
            allow_grid_charging=allow_grid_charging,
        )

        grid_import_kw = np.array(result.hourly_grid_import_kw)
        grid_import_kwh = grid_import_kw * dt_hours
        cap_fee = compute_capacity_fee(grid_import_kwh, time_index, capacity_fee_config)

        grid_export_kw = np.array(result.hourly_grid_export_kw) if result.hourly_grid_export_kw else np.zeros(n)
        energy_cost = (
            float(np.sum(grid_import_kw * base_buy) * dt_hours) -
            float(np.sum(grid_export_kw * base_sell) * dt_hours)
        )
        total_cost = energy_cost + cap_fee.total_fee_pln

        attempt = {
            'premium': premium,
            'energy_cost': energy_cost,
            'capacity_fee': cap_fee.total_fee_pln,
            'total_cost': total_cost,
            'avg_delta_s': cap_fee.avg_delta_s,
            'k_histogram': cap_fee.k_histogram,
        }
        all_attempts.append(attempt)

        logger.info(
            f"Cap-fee multi-solve: premium={premium:.4f}, "
            f"energy={energy_cost:.0f}, cap_fee={cap_fee.total_fee_pln:.0f}, "
            f"total={total_cost:.0f}, Δs={cap_fee.avg_delta_s:.1f}%"
        )

        if total_cost < best_total_cost:
            best_total_cost = total_cost
            best_result = result
            best_cap_fee_info = {
                'total_fee_pln': cap_fee.total_fee_pln,
                'avg_delta_s': cap_fee.avg_delta_s,
                'k_histogram': cap_fee.k_histogram,
                'monthly_results': [
                    {'month': m.month, 'fee_pln': m.total_fee_pln, 'avg_delta_s': m.avg_delta_s}
                    for m in cap_fee.monthly_results
                ],
            }
            best_premium = premium

    if best_result:
        best_result.info = best_result.info or {}
        best_result.info['capacity_fee_optimization'] = {
            'method': 'multi_solve_premium',
            'best_premium_pln_kwh': best_premium,
            'total_cost_pln': best_total_cost,
            'capacity_fee_pln': best_cap_fee_info['total_fee_pln'] if best_cap_fee_info else 0,
            'avg_delta_s': best_cap_fee_info['avg_delta_s'] if best_cap_fee_info else 0,
            'k_histogram': best_cap_fee_info['k_histogram'] if best_cap_fee_info else {},
            'premiums_tried': len(premium_levels),
            'all_attempts': all_attempts,
        }

    return best_result, best_cap_fee_info


# =============================================================================
# NLP Solver Fallback (SLSQP for nonlinear constraints)
# =============================================================================

def _nlp_dispatch_fallback(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    soc_init: float,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    time_limit: float = 30.0,
) -> Optional[np.ndarray]:
    """
    NLP solver fallback using scipy.optimize.minimize (SLSQP).

    Used when LP relaxation fails at level 2+.
    Handles nonlinear constraints better (e.g., SoH-dependent degradation).

    Returns SoC trajectory (normalized 0-1) or None if fails.
    """
    from scipy.optimize import minimize

    n = len(pv_kw)
    cap = battery.energy_kwh
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge
    c_rate = battery.power_kw / cap if cap > 0 else 0.0

    if cap <= 0 or n == 0:
        return None

    soc_lo = battery.soc_min
    soc_hi = battery.soc_max

    # Objective: minimize energy cost
    def objective(soc_vec):
        cost = 0.0
        prev_soc = soc_init
        for t in range(n):
            dsoc = soc_vec[t] - prev_soc
            if dsoc > 0:
                # Charging
                power_from_source = dsoc * cap / (eta_ch * dt_hours)
                net_power = load_kw[t] - pv_kw[t] + power_from_source
            else:
                # Discharging
                power_delivered = -dsoc * cap * eta_dis / dt_hours
                net_power = load_kw[t] - pv_kw[t] - power_delivered

            if net_power > 0:
                cost += net_power * buy_price[t] * dt_hours
            else:
                cost += net_power * sell_price[t] * dt_hours
            prev_soc = soc_vec[t]
        return cost

    # Constraints
    constraints = []

    # C-rate constraint
    def c_rate_constraint(soc_vec):
        violations = np.zeros(2 * n)
        prev_soc = soc_init
        for t in range(n):
            dsoc_dt = (soc_vec[t] - prev_soc) / dt_hours
            violations[t] = c_rate - dsoc_dt       # dsoc/dt <= c_rate
            violations[n + t] = c_rate + dsoc_dt    # dsoc/dt >= -c_rate
            prev_soc = soc_vec[t]
        return violations

    constraints.append({'type': 'ineq', 'fun': c_rate_constraint})

    # Peak shaving constraint
    if peak_limit_kw is not None and mode in (DispatchMode.PEAK_SHAVING, DispatchMode.STACKED):
        def peak_constraint(soc_vec):
            violations = np.zeros(n)
            prev_soc = soc_init
            for t in range(n):
                dsoc = soc_vec[t] - prev_soc
                if dsoc < 0:
                    power_delivered = -dsoc * cap * eta_dis / dt_hours
                else:
                    power_delivered = 0.0
                grid_import = load_kw[t] - pv_kw[t] - power_delivered
                violations[t] = peak_limit_kw - grid_import
                prev_soc = soc_vec[t]
            return violations

        constraints.append({'type': 'ineq', 'fun': peak_constraint})

    # Initial guess: hold SoC
    x0 = np.full(n, soc_init)
    bounds = [(soc_lo, soc_hi)] * n

    try:
        result = minimize(
            objective, x0, method='SLSQP',
            bounds=bounds, constraints=constraints,
            options={'maxiter': 200, 'ftol': 1e-6, 'disp': False},
        )
        if result.success or result.fun < objective(x0):
            return result.x
    except Exception as e:
        logger.warning(f"NLP solver exception: {e}")

    return None


# =============================================================================
# Enhanced solve_lp_window with NLP fallback
# =============================================================================

def solve_lp_window_enhanced(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    buy_price: np.ndarray,
    sell_price: np.ndarray,
    soc_init: float,
    mode: DispatchMode,
    peak_limit_kw: Optional[float] = None,
    time_limit: float = 30.0,
    grid_connection_kw: Optional[float] = None,
    use_nlp_fallback: bool = True,
) -> Optional[np.ndarray]:
    """
    Enhanced LP solver with NLP fallback.

    Relaxation levels:
      0. Original LP constraints
      1. Relaxed peak limit (+50%)
      2. NLP solver (SLSQP) — NEW
      3. No peak limit LP
      4. No peak limit + full SoC range LP

    Returns SoC trajectory or None.
    """
    n = len(pv_kw)
    if battery.energy_kwh <= 0 or n == 0:
        return None

    # Level 0: original LP
    result = _try_solve_lp_core(
        pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
        soc_init, mode, peak_limit_kw, time_limit,
        grid_connection_kw=grid_connection_kw,
    )
    if result is not None:
        return result

    # Level 1: relaxed peak limit
    if peak_limit_kw is not None:
        result = _try_solve_lp_core(
            pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
            soc_init, mode, peak_limit_kw * 1.5, time_limit,
            grid_connection_kw=grid_connection_kw,
        )
        if result is not None:
            logger.info("Enhanced LP: solved with relaxed peak (x1.5)")
            return result

    # Level 2: NLP fallback (SLSQP)
    if use_nlp_fallback and n <= 96:  # NLP only for short windows (≤4 days)
        result = _nlp_dispatch_fallback(
            pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
            soc_init, mode, peak_limit_kw, time_limit,
        )
        if result is not None:
            logger.info("Enhanced LP: solved with NLP fallback (SLSQP)")
            return result

    # Level 3: no peak limit LP
    if peak_limit_kw is not None:
        result = _try_solve_lp_core(
            pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
            soc_init, mode, None, time_limit,
            grid_connection_kw=grid_connection_kw,
        )
        if result is not None:
            logger.info("Enhanced LP: solved without peak limit")
            return result

    # Level 4: full relaxation
    result = _try_solve_lp_core(
        pv_kw, load_kw, battery, dt_hours, buy_price, sell_price,
        soc_init, mode, None, time_limit,
        soc_min_override=0.0, soc_max_override=1.0,
        grid_connection_kw=None,
    )
    if result is not None:
        logger.info("Enhanced LP: solved with full relaxation")
        return result

    return None


# =============================================================================
# Peak Shaving Optimizer
# =============================================================================

def optimize_peak_shaving(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float = 1.0,
    target_reduction_pct: float = 20.0,
    n_iterations: int = 10,
    lp_config: Optional[LPSolverParams] = None,
    grid_connection_kw: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Iterative peak shaving optimizer.

    Finds the minimum achievable peak by binary search on peak_limit_kw.
    Uses LP dispatch at each iteration to check feasibility.

    Returns:
        Dict with optimal_peak_kw, reduction_pct, reduction_kw,
        annual_demand_charge_savings_pln, iterations.
    """
    original_peak = float(np.max(load_kw - pv_kw))
    if original_peak <= 0:
        return {
            "original_peak_kw": 0,
            "optimal_peak_kw": 0,
            "reduction_kw": 0,
            "reduction_pct": 0,
            "feasible": True,
            "iterations": 0,
        }

    # Binary search for minimum feasible peak
    lo = max(original_peak * 0.3, battery.power_kw * 0.1)  # Don't go below 30% or battery can't help
    hi = original_peak
    best_feasible_peak = original_peak

    buy_price = np.full(len(load_kw), 0.5)   # Dummy prices for feasibility check
    sell_price = np.full(len(load_kw), 0.05)

    for i in range(n_iterations):
        mid = (lo + hi) / 2

        soc = solve_lp_window(
            pv_kw=pv_kw[:min(len(pv_kw), 168)],  # Test on 1 week
            load_kw=load_kw[:min(len(load_kw), 168)],
            battery=battery,
            dt_hours=dt_hours,
            buy_price=buy_price[:min(len(buy_price), 168)],
            sell_price=sell_price[:min(len(sell_price), 168)],
            soc_init=battery.soc_initial,
            mode=DispatchMode.PEAK_SHAVING,
            peak_limit_kw=mid,
            time_limit=5.0,
            grid_connection_kw=grid_connection_kw,
        )

        if soc is not None:
            # Feasible — try lower
            best_feasible_peak = mid
            hi = mid
        else:
            # Infeasible — try higher
            lo = mid

    reduction_kw = original_peak - best_feasible_peak
    reduction_pct = reduction_kw / original_peak * 100 if original_peak > 0 else 0

    return {
        "original_peak_kw": round(original_peak, 2),
        "optimal_peak_kw": round(best_feasible_peak, 2),
        "reduction_kw": round(reduction_kw, 2),
        "reduction_pct": round(reduction_pct, 1),
        "feasible": best_feasible_peak < original_peak,
        "iterations": n_iterations,
    }
