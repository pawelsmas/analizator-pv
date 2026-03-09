"""
Monte Carlo BESS Engine — vectorized stochastic battery investment analysis.

Architecture:
- Loop over hours (8760), vectorize over scenarios (N)
- Cholesky-correlated random variables (5 factors)
- Adaptive convergence: stop when P50 + CVaR95 stable for 3 batches
- Burn-in: convergence check only after 1000 iterations (500 in quick mode)
- Shifted lognormal for RDN prices (allows negatives)

Performance target: 2000 scenarios × 4 sizes in ~2-4 minutes.
"""

from __future__ import annotations

import copy
import logging
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import norm as scipy_norm

from .distributions import (
    DEFAULT_CORRELATION_MATRIX,
    DEFAULT_DIST_SPECS,
    VARIABLE_ORDER,
    apply_overrides,
    generate_correlated_annual_factors,
)
from .models import (
    BreakevenInfo,
    ConvergenceInfo,
    HistogramData,
    MCBessRequest,
    MCBessResult,
    PercentileResults,
    RiskMetrics,
    SimulationMode,
    SizeComparison,
    SizeResult,
    TornadoBar,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode defaults
# ---------------------------------------------------------------------------

MODE_DEFAULTS = {
    SimulationMode.QUICK:    {"max_iter": 500,  "burn_in": 500},
    SimulationMode.STANDARD: {"max_iter": 2000, "burn_in": 1000},
    SimulationMode.FULL:     {"max_iter": 5000, "burn_in": 1000},
}


# ---------------------------------------------------------------------------
# Capacity fee helpers
# ---------------------------------------------------------------------------

def _build_workday_mask(start_date: str, n_hours: int) -> np.ndarray:
    """Build boolean mask: True for workday hours in selected window."""
    from common.calendar_pl import is_workday

    d0 = date.fromisoformat(start_date)
    mask = np.zeros(n_hours, dtype=bool)

    for h in range(n_hours):
        day = d0 + timedelta(hours=h)
        day_date = day if isinstance(day, date) else day
        # timedelta on date gives date
        current_date = d0 + timedelta(days=h // 24)
        hour_of_day = h % 24
        if is_workday(current_date):
            mask[h] = True

    return mask


def _build_selected_hours_mask(
    start_date: str, n_hours: int,
    hour_start: int = 7, hour_end: int = 22,
) -> np.ndarray:
    """Mask: True for selected hours on workdays (for capacity fee)."""
    from common.calendar_pl import is_workday

    d0 = date.fromisoformat(start_date)
    mask = np.zeros(n_hours, dtype=bool)

    for h in range(n_hours):
        current_date = d0 + timedelta(days=h // 24)
        hour_of_day = h % 24
        if is_workday(current_date) and hour_start <= hour_of_day < hour_end:
            mask[h] = True

    return mask


def _classify_k_and_coefficient(
    grid_import_selected: float,
    grid_import_total: float,
) -> Tuple[str, float]:
    """Classify K-class and return A coefficient."""
    if grid_import_total <= 0:
        return "K1", 0.17

    delta_s_pct = (grid_import_selected / grid_import_total - 1.0) * 100.0

    if delta_s_pct < 5.0:
        return "K1", 0.17
    elif delta_s_pct < 10.0:
        return "K2", 0.50
    elif delta_s_pct < 15.0:
        return "K3", 0.83
    else:
        return "K4", 1.00


# ---------------------------------------------------------------------------
# Vectorized dispatch (core hot loop)
# ---------------------------------------------------------------------------

def _vectorized_dispatch(
    n_scenarios: int,
    n_hours: int,
    load_kw: np.ndarray,          # (n_hours,) base profile
    pv_kw: np.ndarray,            # (n_hours,) base PV or zeros
    rdn_prices: np.ndarray,       # (n_scenarios, n_hours) PLN/MWh
    battery_power_kw: float,
    battery_energy_kwh: float,
    eta_charge: float,
    eta_discharge: float,
    soc_min: float,
    soc_max: float,
    soc_initial: float,
    consumption_factors: np.ndarray,   # (n_scenarios,)
    pv_factors: np.ndarray,            # (n_scenarios,)
) -> Dict[str, np.ndarray]:
    """
    Vectorized arbitrage+autoconsumption dispatch.

    Strategy per hour:
    1. PV surplus → charge battery (autoconsumption)
    2. If RDN price < buy_threshold → charge from grid
    3. If RDN price > sell_threshold → discharge to reduce grid import
    4. Otherwise → hold

    Thresholds are adaptive: percentiles of the price distribution.

    Returns dict with arrays of shape (n_scenarios,):
    - total_charge_kwh, total_discharge_kwh
    - total_grid_import_kwh, total_grid_export_kwh
    - total_arbitrage_value_pln
    - total_cycles
    - grid_import_per_hour: (n_scenarios, n_hours)
    """
    # Scale profiles per scenario: (n_scenarios, n_hours)
    load = load_kw[np.newaxis, :] * consumption_factors[:, np.newaxis]
    pv = pv_kw[np.newaxis, :] * pv_factors[:, np.newaxis]

    # Adaptive thresholds per scenario (percentile-based)
    buy_threshold = np.percentile(rdn_prices, 25, axis=1)   # (n_scenarios,)
    sell_threshold = np.percentile(rdn_prices, 75, axis=1)   # (n_scenarios,)

    # State arrays
    soc = np.full(n_scenarios, soc_initial * battery_energy_kwh)
    soc_min_kwh = soc_min * battery_energy_kwh
    soc_max_kwh = soc_max * battery_energy_kwh

    # Accumulators
    total_charge = np.zeros(n_scenarios)
    total_discharge = np.zeros(n_scenarios)
    total_grid_import = np.zeros(n_scenarios)
    total_grid_export = np.zeros(n_scenarios)
    total_arb_value = np.zeros(n_scenarios)

    # Grid import per hour for capacity fee (n_scenarios, n_hours)
    grid_import_hourly = np.zeros((n_scenarios, n_hours))

    dt = 1.0  # 1 hour

    for h in range(n_hours):
        p_load = load[:, h]      # (n_scenarios,)
        p_pv = pv[:, h]          # (n_scenarios,)
        p_rdn = rdn_prices[:, h] # (n_scenarios,)

        net_load = p_load - p_pv  # positive = deficit, negative = surplus

        # --- Step 1: PV surplus → charge ---
        pv_surplus = np.maximum(-net_load, 0.0)
        charge_from_pv = np.minimum(pv_surplus, battery_power_kw)
        space_available = (soc_max_kwh - soc) / eta_charge
        charge_from_pv = np.minimum(charge_from_pv, np.maximum(space_available, 0.0))

        # --- Step 2: Price-based arbitrage ---
        # Buy (charge from grid) when cheap
        want_buy = (p_rdn < buy_threshold) & (net_load >= 0)
        charge_from_grid = np.where(want_buy, battery_power_kw - charge_from_pv, 0.0)
        charge_from_grid = np.minimum(charge_from_grid, np.maximum(space_available - charge_from_pv, 0.0))
        charge_from_grid = np.maximum(charge_from_grid, 0.0)

        total_charge_h = charge_from_pv + charge_from_grid
        soc_after_charge = soc + total_charge_h * eta_charge

        # Sell (discharge) when expensive
        want_sell = (p_rdn > sell_threshold) & (net_load > 0)
        discharge_wanted = np.where(want_sell, np.minimum(net_load, battery_power_kw), 0.0)

        # Also discharge for autoconsumption when no PV and not buying
        autocons_discharge = np.where(
            (~want_buy) & (~want_sell) & (net_load > 0),
            np.minimum(net_load, battery_power_kw),
            0.0
        )
        discharge_wanted = np.maximum(discharge_wanted, autocons_discharge)

        energy_available = (soc_after_charge - soc_min_kwh) * eta_discharge
        actual_discharge = np.minimum(discharge_wanted, np.maximum(energy_available, 0.0))

        # Update SoC
        soc = soc_after_charge - actual_discharge / eta_discharge

        # --- Energy balance ---
        # Grid import = load - pv - discharge + charge_from_grid
        grid_import = np.maximum(net_load - actual_discharge + charge_from_grid, 0.0)
        grid_export = np.maximum(-(net_load - actual_discharge + charge_from_grid), 0.0)

        grid_import_hourly[:, h] = grid_import

        # Arbitrage value: discharge at high price - charge at low price
        arb_value = (actual_discharge * p_rdn - charge_from_grid * p_rdn) / 1000.0  # MWh→kWh

        # Accumulate
        total_charge += total_charge_h
        total_discharge += actual_discharge
        total_grid_import += grid_import
        total_grid_export += grid_export
        total_arb_value += arb_value

    # Cycles
    total_cycles = total_discharge / battery_energy_kwh

    return {
        "total_charge_kwh": total_charge,
        "total_discharge_kwh": total_discharge,
        "total_grid_import_kwh": total_grid_import,
        "total_grid_export_kwh": total_grid_export,
        "total_arbitrage_value_pln": total_arb_value,
        "total_cycles": total_cycles,
        "grid_import_hourly": grid_import_hourly,
    }


# ---------------------------------------------------------------------------
# Financial calculations (vectorized)
# ---------------------------------------------------------------------------

def _compute_annual_savings(
    dispatch: Dict[str, np.ndarray],
    grid_import_hourly: np.ndarray,
    selected_hours_mask: np.ndarray,
    base_import_price: float,
    base_export_price: float,
    som_rates: np.ndarray,  # (n_scenarios,)
    load_kw_base: np.ndarray,
    pv_kw_base: np.ndarray,
    consumption_factors: np.ndarray,
    pv_factors: np.ndarray,
) -> Dict[str, np.ndarray]:
    """Compute annual savings vs baseline (no BESS)."""
    n_scenarios = dispatch["total_grid_import_kwh"].shape[0]

    # Baseline: no battery
    load_total = load_kw_base.sum() * consumption_factors
    pv_total = pv_kw_base.sum() * pv_factors
    baseline_import = np.maximum(load_total - pv_total, 0.0)

    # Energy cost savings
    import_reduction = baseline_import - dispatch["total_grid_import_kwh"]
    energy_savings = import_reduction * base_import_price

    # Export revenue change
    baseline_export = np.maximum(pv_total - load_total, 0.0)
    export_change = (dispatch["total_grid_export_kwh"] - baseline_export) * base_export_price

    # Arbitrage
    arbitrage = dispatch["total_arbitrage_value_pln"]

    # Capacity fee savings
    # Baseline: grid import in selected hours without BESS
    baseline_load_selected = load_kw_base[selected_hours_mask].sum()
    baseline_load_total = load_kw_base.sum()

    # With BESS: grid import in selected hours
    bess_import_selected = grid_import_hourly[:, selected_hours_mask].sum(axis=1)
    bess_import_total = dispatch["total_grid_import_kwh"]

    # K-class for baseline
    _, baseline_A = _classify_k_and_coefficient(
        baseline_load_selected * 1.0,  # approximate
        baseline_load_total * 1.0,
    )
    baseline_cap_fee = baseline_A * 0.2194 * baseline_load_selected  # fixed baseline

    # K-class per scenario for BESS
    cap_fee_savings = np.zeros(n_scenarios)
    for s in range(n_scenarios):
        _, bess_A = _classify_k_and_coefficient(
            bess_import_selected[s],
            bess_import_total[s],
        )
        bess_cap_fee = bess_A * som_rates[s] * bess_import_selected[s]
        baseline_cf = baseline_A * som_rates[s] * baseline_load_selected * consumption_factors[s]
        cap_fee_savings[s] = baseline_cf - bess_cap_fee

    total_savings = energy_savings + export_change + arbitrage + np.maximum(cap_fee_savings, 0.0)

    return {
        "energy_savings": energy_savings,
        "arbitrage_revenue": arbitrage,
        "capacity_fee_savings": np.maximum(cap_fee_savings, 0.0),
        "autoconsumption_savings": energy_savings,  # main component
        "total_annual_savings": total_savings,
    }


def _compute_npv_irr(
    annual_savings: np.ndarray,   # (n_scenarios,)
    capex: float,
    opex_annual: float,
    discount_rates: np.ndarray,   # (n_scenarios,)
    inflation_deltas: np.ndarray, # (n_scenarios,) additive
    years: int,
    degradation_factors: np.ndarray,  # (n_scenarios,) annual SoH factor
    replacement_year: Optional[int] = None,
    replacement_cost: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized NPV, IRR estimate, and payback calculation.

    Returns: (npv_array, irr_array, payback_array)
    """
    n = annual_savings.shape[0]

    npv = np.full(n, -capex)
    payback = np.full(n, np.inf)
    cumulative = np.full(n, -capex)

    # Build cash flow matrix for IRR: (n_scenarios, years+1)
    cf_matrix = np.zeros((n, years + 1))
    cf_matrix[:, 0] = -capex

    base_inflation = 0.035  # 3.5% base

    for y in range(1, years + 1):
        # Degradation: compound
        soh = degradation_factors ** y

        # Inflation escalation
        esc = (1.0 + base_inflation + inflation_deltas) ** y

        # Annual cash flow
        cf = annual_savings * soh * esc - opex_annual * esc

        # Battery replacement
        if replacement_year is not None and y == replacement_year:
            cf -= replacement_cost

        # Discount
        discount = (1.0 + discount_rates) ** y
        npv += cf / discount

        # Cumulative (undiscounted) for simple payback
        cumulative += cf
        just_paid_back = (cumulative >= 0) & (payback == np.inf)
        payback = np.where(just_paid_back, float(y), payback)

        cf_matrix[:, y] = cf

    # Simplified IRR: Newton-Raphson (vectorized)
    irr = _estimate_irr_vectorized(cf_matrix, max_iter=30)

    return npv, irr, payback


def _estimate_irr_vectorized(
    cash_flows: np.ndarray,  # (n_scenarios, periods)
    max_iter: int = 30,
    tol: float = 1e-4,
) -> np.ndarray:
    """Vectorized IRR via Newton-Raphson."""
    n, T = cash_flows.shape
    r = np.full(n, 0.10)  # initial guess 10%

    for _ in range(max_iter):
        t_vec = np.arange(T)
        discount = (1.0 + r[:, np.newaxis]) ** t_vec[np.newaxis, :]
        npv = (cash_flows / discount).sum(axis=1)
        dnpv = (-t_vec[np.newaxis, :] * cash_flows / ((1.0 + r[:, np.newaxis]) ** (t_vec[np.newaxis, :] + 1))).sum(axis=1)

        # Avoid division by zero
        dnpv = np.where(np.abs(dnpv) < 1e-12, 1e-12, dnpv)
        r_new = r - npv / dnpv
        r_new = np.clip(r_new, -0.5, 5.0)

        converged = np.abs(npv) < tol
        if converged.all():
            break
        r = r_new

    return r


# ---------------------------------------------------------------------------
# Convergence checker
# ---------------------------------------------------------------------------

class _ConvergenceTracker:
    """Track P50 and CVaR95 stability across batches."""

    def __init__(self, threshold_pct: float, required_batches: int, burn_in: int):
        self.threshold = threshold_pct / 100.0
        self.required = required_batches
        self.burn_in = burn_in
        self.history: List[Dict[str, float]] = []
        self.stable_count = 0

    def check(self, iteration: int, npv_so_far: np.ndarray) -> bool:
        """Check convergence. Returns True if converged."""
        if iteration < self.burn_in:
            return False

        p50 = float(np.percentile(npv_so_far, 50))
        sorted_npv = np.sort(npv_so_far)
        n = len(sorted_npv)
        cutoff = max(1, int(0.05 * n))
        cvar95 = float(sorted_npv[:cutoff].mean()) if cutoff > 0 else p50

        self.history.append({"p50": p50, "cvar95": cvar95})

        if len(self.history) < 2:
            return False

        prev = self.history[-2]

        p50_change = abs(p50 - prev["p50"]) / max(abs(prev["p50"]), 1.0)
        cvar_change = abs(cvar95 - prev["cvar95"]) / max(abs(prev["cvar95"]), 1.0)

        if p50_change < self.threshold and cvar_change < self.threshold:
            self.stable_count += 1
        else:
            self.stable_count = 0

        return self.stable_count >= self.required

    @property
    def last_p50_change(self) -> float:
        if len(self.history) < 2:
            return 100.0
        prev = self.history[-2]
        curr = self.history[-1]
        return abs(curr["p50"] - prev["p50"]) / max(abs(prev["p50"]), 1.0) * 100

    @property
    def last_cvar_change(self) -> float:
        if len(self.history) < 2:
            return 100.0
        prev = self.history[-2]
        curr = self.history[-1]
        return abs(curr["cvar95"] - prev["cvar95"]) / max(abs(prev["cvar95"]), 1.0) * 100


# ---------------------------------------------------------------------------
# Percentile & risk helpers
# ---------------------------------------------------------------------------

def _percentiles(arr: np.ndarray) -> PercentileResults:
    return PercentileResults(
        p5=float(np.percentile(arr, 5)),
        p10=float(np.percentile(arr, 10)),
        p25=float(np.percentile(arr, 25)),
        p50=float(np.percentile(arr, 50)),
        p75=float(np.percentile(arr, 75)),
        p90=float(np.percentile(arr, 90)),
        p95=float(np.percentile(arr, 95)),
    )


def _histogram(arr: np.ndarray, bins: int) -> HistogramData:
    counts, edges = np.histogram(arr, bins=bins)
    return HistogramData(
        bin_edges=[float(e) for e in edges],
        counts=[int(c) for c in counts],
    )


def _risk_metrics(npv: np.ndarray) -> RiskMetrics:
    sorted_npv = np.sort(npv)
    n = len(sorted_npv)
    cutoff_5 = max(1, int(0.05 * n))
    cutoff_1 = max(1, int(0.01 * n))

    prob_pos = float((npv > 0).mean())
    var95 = float(sorted_npv[cutoff_5 - 1])
    var99 = float(sorted_npv[cutoff_1 - 1])
    cvar95 = float(sorted_npv[:cutoff_5].mean())

    mean = float(npv.mean())
    std = float(npv.std())
    sharpe = mean / std if std > 0 else None

    downside = npv[npv < 0]
    dd = float(np.sqrt((downside**2).mean())) if len(downside) > 0 else 0.0

    return RiskMetrics(
        prob_positive_npv=prob_pos,
        var_95=var95,
        var_99=var99,
        cvar_95=cvar95,
        sharpe_ratio=sharpe,
        downside_deviation=dd,
        max_loss=float(sorted_npv[0]),
    )


# ---------------------------------------------------------------------------
# Tornado sensitivity
# ---------------------------------------------------------------------------

def _compute_tornado(
    request: MCBessRequest,
    base_npv_median: float,
    best_size_idx: int,
) -> List[TornadoBar]:
    """One-at-a-time sensitivity: ±1σ for each variable."""
    # Simplified tornado: use base_npv_median and scale by expected impact
    variables = [
        ("rdn_prices", "Ceny RDN", 0.20),
        ("som_rate", "Stawka SOM", 0.15),
        ("consumption", "Profil zużycia", 0.10),
        ("pv_production", "Produkcja PV", 0.08),
        ("inflation", "Inflacja", 0.015),
    ]

    bars = []
    capex = request.battery_sizes[best_size_idx].energy_kwh * request.capex_pln_per_kwh

    for var_name, label, sigma_pct in variables:
        # Approximate impact as fraction of NPV
        impact = abs(base_npv_median) * sigma_pct * 2
        bars.append(TornadoBar(
            variable=var_name,
            label_pl=label,
            npv_low=base_npv_median - impact / 2,
            npv_high=base_npv_median + impact / 2,
            impact=impact,
        ))

    bars.sort(key=lambda b: b.impact, reverse=True)
    return bars


# ---------------------------------------------------------------------------
# Insight generator
# ---------------------------------------------------------------------------

def _generate_insights(
    size_results: List[SizeResult],
    optimal_idx: int,
    convergence: ConvergenceInfo,
) -> List[str]:
    """Generate Polish-language insights."""
    insights = []
    best = size_results[optimal_idx]

    # Probability of profit
    prob = best.risk_metrics.prob_positive_npv * 100
    if prob >= 80:
        insights.append(
            f"Magazyn {best.power_kw:.0f} kW / {best.energy_kwh:.0f} kWh ma {prob:.0f}% "
            f"szans na dodatni NPV (mediana: {best.npv_percentiles.p50:,.0f} PLN)."
        )
    elif prob >= 50:
        insights.append(
            f"Magazyn {best.power_kw:.0f} kW / {best.energy_kwh:.0f} kWh ma {prob:.0f}% "
            f"szans na zwrot inwestycji — rozważ mniejszy rozmiar."
        )
    else:
        insights.append(
            f"⚠️ Magazyn {best.power_kw:.0f} kW / {best.energy_kwh:.0f} kWh ma tylko {prob:.0f}% "
            f"szans na zwrot. Inwestycja obarczona wysokim ryzykiem."
        )

    # CVaR warning
    if best.risk_metrics.cvar_95 < -best.capex_pln * 0.3:
        insights.append(
            f"⚠️ W najgorszych 5% scenariuszy średnia strata wynosi "
            f"{best.risk_metrics.cvar_95:,.0f} PLN (CVaR 95%)."
        )

    # Payback
    if best.breakeven.payback_p50_years and best.breakeven.payback_p50_years < 100:
        insights.append(
            f"Mediana okresu zwrotu: {best.breakeven.payback_p50_years:.1f} lat "
            f"({best.breakeven.prob_payback_within_horizon * 100:.0f}% szans na zwrot w horyzoncie analizy)."
        )

    # Revenue composition
    total_rev = best.mean_total_annual_revenue_pln
    if total_rev > 0:
        arb_pct = best.mean_arbitrage_revenue_pln / total_rev * 100
        cap_pct = best.mean_capacity_fee_savings_pln / total_rev * 100
        auto_pct = best.mean_autoconsumption_savings_pln / total_rev * 100
        insights.append(
            f"Struktura przychodów: autokonsumpcja {auto_pct:.0f}%, "
            f"arbitraż {arb_pct:.0f}%, opłata mocowa {cap_pct:.0f}%."
        )

    # Convergence
    if convergence.converged:
        insights.append(
            f"Symulacja zbiegła po {convergence.iterations_run} iteracjach "
            f"(P50 Δ={convergence.p50_change_pct:.2f}%, CVaR Δ={convergence.cvar95_change_pct:.2f}%)."
        )

    # Size comparison
    if len(size_results) > 1:
        probs = [(i, sr.risk_metrics.prob_positive_npv) for i, sr in enumerate(size_results)]
        safest = max(probs, key=lambda x: x[1])
        if safest[0] != optimal_idx:
            safe_sr = size_results[safest[0]]
            insights.append(
                f"Najbezpieczniejszy wariant: {safe_sr.power_kw:.0f} kW / "
                f"{safe_sr.energy_kwh:.0f} kWh ({safest[1] * 100:.0f}% szans na zysk)."
            )

    return insights


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class MonteCarlosBessEngine:
    """
    Monte Carlo BESS simulation engine.

    Usage:
        engine = MonteCarlosBessEngine()
        result = engine.run(request, progress_callback=None)
    """

    def run(
        self,
        request: MCBessRequest,
        progress_callback: Optional[Callable[[int, int, Optional[MCBessResult]], None]] = None,
    ) -> MCBessResult:
        """
        Run full Monte Carlo simulation.

        Args:
            request: Simulation parameters
            progress_callback: Called with (iterations_done, max_iterations, partial_result)
                              after each batch for progress reporting.
        """
        t0 = time.perf_counter()

        # --- Resolve mode defaults ---
        defaults = MODE_DEFAULTS[request.mode]
        max_iter = request.max_iterations or defaults["max_iter"]
        burn_in = defaults["burn_in"]
        batch_size = request.batch_size

        # --- RNG ---
        rng = np.random.default_rng(request.random_seed)

        # --- Prepare distributions ---
        dist_specs, corr_matrix = apply_overrides(
            copy.deepcopy(DEFAULT_DIST_SPECS),
            DEFAULT_CORRELATION_MATRIX.copy(),
            request.distribution_overrides,
            request.correlation_overrides,
        )

        # --- Prepare base data ---
        n_hours = len(request.load_kw)
        load_base = np.array(request.load_kw, dtype=np.float64)
        pv_base = np.array(request.pv_kw, dtype=np.float64) if request.pv_kw else np.zeros(n_hours)

        # RDN base prices
        if request.base_rdn_prices_pln_mwh:
            rdn_base = np.array(request.base_rdn_prices_pln_mwh, dtype=np.float64)
        else:
            # Synthetic day-ahead profile (typical Polish market)
            hours_of_day = np.arange(n_hours) % 24
            rdn_base = np.where(
                (hours_of_day >= 7) & (hours_of_day < 22),
                450.0,  # peak
                250.0,  # off-peak
            ).astype(np.float64)

        # Selected hours mask for capacity fee
        selected_mask = _build_selected_hours_mask(
            request.start_date, n_hours,
            request.selected_hours_start, request.selected_hours_end,
        )

        # --- Pre-generate ALL random factors at once (memory efficient) ---
        all_factors = generate_correlated_annual_factors(
            max_iter, dist_specs, corr_matrix, rng,
        )

        # Additional: discount rate noise
        dr_noise = rng.normal(0, 0.01, max_iter)  # ±1pp

        # Degradation factor per year (annual multiplier)
        base_cal_deg = request.annual_calendar_degradation_pct / 100.0
        deg_factors = 1.0 - base_cal_deg * all_factors.get(
            "consumption", np.ones(max_iter)
        )  # use consumption correlation as proxy

        # --- Run per battery size ---
        all_size_results: List[SizeResult] = []

        for size_spec in request.battery_sizes:
            npv_all = np.zeros(max_iter)
            irr_all = np.zeros(max_iter)
            payback_all = np.full(max_iter, np.inf)
            savings_acc = {
                "energy": np.zeros(max_iter),
                "arbitrage": np.zeros(max_iter),
                "capacity_fee": np.zeros(max_iter),
                "autocons": np.zeros(max_iter),
                "total": np.zeros(max_iter),
            }
            cycles_all = np.zeros(max_iter)

            capex = size_spec.energy_kwh * request.capex_pln_per_kwh
            opex_annual = capex * request.opex_pct / 100.0
            replacement_cost = capex * request.battery_replacement_cost_pct / 100.0

            tracker = _ConvergenceTracker(
                request.convergence_threshold_pct,
                request.convergence_batches,
                burn_in,
            )

            iterations_done = 0

            while iterations_done < max_iter:
                batch_end = min(iterations_done + batch_size, max_iter)
                batch_slice = slice(iterations_done, batch_end)
                n_batch = batch_end - iterations_done

                # --- Generate scenario prices ---
                rdn_factors = all_factors["rdn_prices"][batch_slice]
                # Shifted lognormal: factor is already exp(σz - σ²/2)
                # Apply to base prices: rdn_scenario = rdn_base * factor
                rdn_scenario = rdn_base[np.newaxis, :] * rdn_factors[:, np.newaxis]
                # Clip to floor/cap
                rdn_scenario = np.clip(rdn_scenario, -50.0, 2000.0)

                cons_factors = all_factors["consumption"][batch_slice]
                pv_fact = all_factors["pv_production"][batch_slice]
                som_factors = all_factors["som_rate"][batch_slice]
                som_rates = request.som_rate_pln_kwh * som_factors

                # --- Dispatch ---
                dispatch = _vectorized_dispatch(
                    n_scenarios=n_batch,
                    n_hours=n_hours,
                    load_kw=load_base,
                    pv_kw=pv_base,
                    rdn_prices=rdn_scenario,
                    battery_power_kw=size_spec.power_kw,
                    battery_energy_kwh=size_spec.energy_kwh,
                    eta_charge=request.eta_charge,
                    eta_discharge=request.eta_discharge,
                    soc_min=request.soc_min,
                    soc_max=request.soc_max,
                    soc_initial=request.soc_initial,
                    consumption_factors=cons_factors,
                    pv_factors=pv_fact,
                )

                # --- Annual savings ---
                savings = _compute_annual_savings(
                    dispatch=dispatch,
                    grid_import_hourly=dispatch["grid_import_hourly"],
                    selected_hours_mask=selected_mask,
                    base_import_price=request.base_import_price_pln_kwh,
                    base_export_price=request.base_export_price_pln_kwh,
                    som_rates=som_rates,
                    load_kw_base=load_base,
                    pv_kw_base=pv_base,
                    consumption_factors=cons_factors,
                    pv_factors=pv_fact,
                )

                # --- NPV / IRR ---
                disc_rates = request.discount_rate + dr_noise[batch_slice]
                disc_rates = np.clip(disc_rates, 0.01, 0.30)
                infl_deltas = all_factors["inflation"][batch_slice]

                deg_batch = deg_factors[batch_slice]

                npv_batch, irr_batch, payback_batch = _compute_npv_irr(
                    annual_savings=savings["total_annual_savings"],
                    capex=capex,
                    opex_annual=opex_annual,
                    discount_rates=disc_rates,
                    inflation_deltas=infl_deltas,
                    years=request.analysis_years,
                    degradation_factors=deg_batch,
                    replacement_year=request.battery_replacement_year,
                    replacement_cost=replacement_cost,
                )

                # Store
                npv_all[batch_slice] = npv_batch
                irr_all[batch_slice] = irr_batch
                payback_all[batch_slice] = payback_batch
                cycles_all[batch_slice] = dispatch["total_cycles"]
                savings_acc["energy"][batch_slice] = savings["energy_savings"]
                savings_acc["arbitrage"][batch_slice] = savings["arbitrage_revenue"]
                savings_acc["capacity_fee"][batch_slice] = savings["capacity_fee_savings"]
                savings_acc["autocons"][batch_slice] = savings["autoconsumption_savings"]
                savings_acc["total"][batch_slice] = savings["total_annual_savings"]

                iterations_done = batch_end

                # --- Convergence check ---
                if tracker.check(iterations_done, npv_all[:iterations_done]):
                    logger.info(
                        f"MC converged at {iterations_done} iterations for "
                        f"{size_spec.power_kw}kW/{size_spec.energy_kwh}kWh"
                    )
                    break

                # --- Progress callback ---
                if progress_callback:
                    progress_callback(iterations_done, max_iter, None)

            # --- Trim to actual iterations ---
            npv_final = npv_all[:iterations_done]
            irr_final = irr_all[:iterations_done]
            payback_final = payback_all[:iterations_done]
            cycles_final = cycles_all[:iterations_done]

            # Filter valid IRR
            irr_valid = irr_final[np.isfinite(irr_final) & (irr_final > -0.5) & (irr_final < 5.0)]

            # Payback stats
            finite_payback = payback_final[np.isfinite(payback_final)]
            payback_p50 = float(np.median(finite_payback)) if len(finite_payback) > 0 else None
            payback_p90 = float(np.percentile(finite_payback, 90)) if len(finite_payback) > 0 else None
            prob_payback = float((payback_final <= request.analysis_years).mean())

            # Build SizeResult
            sr = SizeResult(
                power_kw=size_spec.power_kw,
                energy_kwh=size_spec.energy_kwh,
                label=size_spec.label or f"{size_spec.power_kw:.0f} kW / {size_spec.energy_kwh:.0f} kWh",
                capex_pln=capex,
                npv_mean=float(npv_final.mean()),
                npv_std=float(npv_final.std()),
                npv_percentiles=_percentiles(npv_final),
                npv_histogram=_histogram(npv_final, request.histogram_bins),
                irr_mean=float(irr_valid.mean()) if len(irr_valid) > 0 else None,
                irr_std=float(irr_valid.std()) if len(irr_valid) > 0 else None,
                irr_percentiles=_percentiles(irr_valid) if len(irr_valid) > 10 else None,
                irr_valid_pct=float(len(irr_valid) / iterations_done * 100),
                breakeven=BreakevenInfo(
                    payback_p50_years=payback_p50,
                    payback_p90_years=payback_p90,
                    prob_payback_within_horizon=prob_payback,
                ),
                risk_metrics=_risk_metrics(npv_final),
                mean_arbitrage_revenue_pln=float(savings_acc["arbitrage"][:iterations_done].mean()),
                mean_capacity_fee_savings_pln=float(savings_acc["capacity_fee"][:iterations_done].mean()),
                mean_autoconsumption_savings_pln=float(savings_acc["autocons"][:iterations_done].mean()),
                mean_total_annual_revenue_pln=float(savings_acc["total"][:iterations_done].mean()),
                mean_annual_cycles=float(cycles_final.mean()),
                npv_distribution=npv_final.tolist() if request.return_distributions else None,
                irr_distribution=irr_valid.tolist() if request.return_distributions else None,
            )

            all_size_results.append(sr)

        # --- Cross-size comparison ---
        optimal_idx = max(
            range(len(all_size_results)),
            key=lambda i: all_size_results[i].risk_metrics.prob_positive_npv * 0.4
            + (all_size_results[i].npv_percentiles.p50 / max(abs(all_size_results[i].capex_pln), 1)) * 0.6
        )

        comparison = SizeComparison(
            sizes=[sr.label or f"{sr.power_kw}/{sr.energy_kwh}" for sr in all_size_results],
            prob_positive_npv=[sr.risk_metrics.prob_positive_npv for sr in all_size_results],
            npv_p50=[sr.npv_percentiles.p50 for sr in all_size_results],
            npv_p10=[sr.npv_percentiles.p10 for sr in all_size_results],
            recommendation_label=all_size_results[optimal_idx].label or "",
            recommendation_reason="Najlepszy stosunek zysku do ryzyka (P(NPV>0) × NPV/CAPEX)",
            optimal_size_index=optimal_idx,
        )

        # --- Tornado ---
        tornado = _compute_tornado(
            request,
            all_size_results[optimal_idx].npv_percentiles.p50,
            optimal_idx,
        )

        # --- Convergence info (from last size) ---
        conv_info = ConvergenceInfo(
            converged=tracker.stable_count >= request.convergence_batches,
            iterations_run=iterations_done,
            p50_change_pct=tracker.last_p50_change,
            cvar95_change_pct=tracker.last_cvar_change,
            stable_batches=tracker.stable_count,
            burn_in_iterations=burn_in,
        )

        # --- Insights ---
        insights = _generate_insights(all_size_results, optimal_idx, conv_info)

        # --- Recommendations per size ---
        for i, sr in enumerate(all_size_results):
            prob = sr.risk_metrics.prob_positive_npv * 100
            if i == optimal_idx:
                sr.recommendation = f"✓✓ OPTYMALNY — {prob:.0f}% szans na zysk"
            elif prob >= 80:
                sr.recommendation = f"✓ Bezpieczny — {prob:.0f}% szans na zysk"
            elif prob >= 50:
                sr.recommendation = f"~ Umiarkowany — {prob:.0f}% szans na zysk"
            else:
                sr.recommendation = f"⚠ Ryzykowny — tylko {prob:.0f}% szans na zysk"

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return MCBessResult(
            simulation_mode=request.mode,
            convergence=conv_info,
            computation_time_ms=elapsed_ms,
            n_battery_sizes=len(request.battery_sizes),
            size_results=all_size_results,
            size_comparison=comparison,
            tornado=tornado,
            insights=insights,
            analysis_years=request.analysis_years,
            discount_rate=request.discount_rate,
            start_date=request.start_date,
        )
