"""
Pydantic models for Monte Carlo BESS simulation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SimulationMode(str, Enum):
    QUICK = "quick"        # 500 iterations, burn-in 500
    STANDARD = "standard"  # 2000 iterations, burn-in 1000
    FULL = "full"          # 5000 iterations, burn-in 1000


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Distribution config
# ---------------------------------------------------------------------------

class DistributionOverride(BaseModel):
    """Override default distribution for a single variable."""
    variable: str = Field(..., description="Variable name: rdn_prices, som_rate, degradation, consumption, pv_production, inflation, discount_rate")
    std_dev_pct: Optional[float] = Field(None, ge=0, le=100, description="Override std dev as % of base value")
    min_val: Optional[float] = None
    max_val: Optional[float] = None


class CorrelationOverride(BaseModel):
    """Override a single correlation pair."""
    var1: str
    var2: str
    correlation: float = Field(..., ge=-1, le=1)


# ---------------------------------------------------------------------------
# Battery sizing variants for MC
# ---------------------------------------------------------------------------

class BatterySizeSpec(BaseModel):
    """One battery size to evaluate in Monte Carlo."""
    power_kw: float = Field(..., gt=0)
    energy_kwh: float = Field(..., gt=0)
    label: Optional[str] = None  # e.g. "100 kW / 200 kWh"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class MCBessRequest(BaseModel):
    """Request for Monte Carlo BESS simulation."""

    # --- Simulation control ---
    mode: SimulationMode = SimulationMode.STANDARD
    max_iterations: Optional[int] = Field(None, ge=100, le=50000,
        description="Override max iterations (if None, uses mode default)")
    convergence_threshold_pct: float = Field(1.0, ge=0.1, le=10.0,
        description="Convergence threshold for adaptive stop (%)")
    convergence_batches: int = Field(3, ge=2, le=10,
        description="Number of consecutive batches that must be stable")
    batch_size: int = Field(200, ge=50, le=1000,
        description="Iterations per convergence check batch")
    random_seed: Optional[int] = Field(None, description="For reproducibility")

    # --- Battery sizes to evaluate ---
    battery_sizes: List[BatterySizeSpec] = Field(
        ..., min_length=1, max_length=10,
        description="Battery sizes to evaluate (1-10)")

    # --- Battery parameters (shared) ---
    eta_charge: float = Field(0.9487, ge=0.5, le=1.0)
    eta_discharge: float = Field(0.9487, ge=0.5, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)
    soc_initial: float = Field(0.50, ge=0.0, le=1.0)

    # --- Load & PV profiles (8760 hourly values) ---
    load_kw: List[float] = Field(..., min_length=8760, max_length=8784,
        description="Hourly load profile [kW]")
    pv_kw: Optional[List[float]] = Field(None, min_length=8760, max_length=8784,
        description="Hourly PV production [kW] (optional)")

    # --- Pricing ---
    base_rdn_prices_pln_mwh: Optional[List[float]] = Field(None,
        min_length=8760, max_length=8784,
        description="Base hourly RDN prices [PLN/MWh]. If None, uses PSE API fallback.")
    base_import_price_pln_kwh: float = Field(0.85,
        description="Base flat import price [PLN/kWh] for cost calculation")
    base_export_price_pln_kwh: float = Field(0.30,
        description="Base flat export price [PLN/kWh]")

    # --- Capacity fee ---
    som_rate_pln_kwh: float = Field(0.2194, description="SOM rate [PLN/kWh]")
    selected_hours_start: int = Field(7, ge=0, le=23)
    selected_hours_end: int = Field(22, ge=1, le=24)

    # --- Finance ---
    capex_pln_per_kwh: float = Field(2500.0, gt=0,
        description="CAPEX [PLN/kWh of storage capacity]")
    opex_pct: float = Field(1.5, ge=0, le=10,
        description="Annual OPEX as % of CAPEX")
    discount_rate: float = Field(0.08, ge=0, le=0.30)
    analysis_years: int = Field(15, ge=5, le=30)
    battery_replacement_year: Optional[int] = Field(None, ge=5, le=25,
        description="Year of battery replacement (None = no replacement)")
    battery_replacement_cost_pct: float = Field(60.0, ge=0, le=100,
        description="Replacement cost as % of original CAPEX")

    # --- Degradation ---
    cycles_to_eol: float = Field(6000, gt=0, description="Cycles to 80% SoH")
    annual_calendar_degradation_pct: float = Field(0.5, ge=0, le=5)

    # --- Start date (for holiday/workday calculation) ---
    start_date: str = Field("2025-01-01", description="YYYY-MM-DD")

    # --- Distribution overrides ---
    distribution_overrides: Optional[List[DistributionOverride]] = None
    correlation_overrides: Optional[List[CorrelationOverride]] = None

    # --- Output control ---
    return_distributions: bool = Field(False,
        description="Return full NPV/IRR arrays for each size (large payload)")
    return_yearly_cashflows: bool = Field(False,
        description="Return yearly cashflow matrix per size")
    histogram_bins: int = Field(50, ge=10, le=200)


# ---------------------------------------------------------------------------
# Result sub-models
# ---------------------------------------------------------------------------

class PercentileResults(BaseModel):
    p5: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float


class HistogramData(BaseModel):
    bin_edges: List[float]
    counts: List[int]


class RiskMetrics(BaseModel):
    prob_positive_npv: float = Field(..., description="P(NPV > 0)")
    var_95: float = Field(..., description="Value at Risk 95%")
    var_99: float = Field(..., description="Value at Risk 99%")
    cvar_95: float = Field(..., description="Conditional VaR (Expected Shortfall) 95%")
    sharpe_ratio: Optional[float] = None
    downside_deviation: Optional[float] = None
    max_loss: float = Field(..., description="Worst-case NPV in simulation")


class ConvergenceInfo(BaseModel):
    converged: bool
    iterations_run: int
    p50_change_pct: float = Field(..., description="Last batch P50 change %")
    cvar95_change_pct: float = Field(..., description="Last batch CVaR95 change %")
    stable_batches: int = Field(..., description="Consecutive stable batches")
    burn_in_iterations: int


class BreakevenInfo(BaseModel):
    payback_p50_years: Optional[float]
    payback_p90_years: Optional[float]
    prob_payback_within_horizon: float = Field(...,
        description="P(payback <= analysis_years)")


class SizeResult(BaseModel):
    """Results for one battery size across all MC scenarios."""
    power_kw: float
    energy_kwh: float
    label: Optional[str] = None
    capex_pln: float

    # NPV
    npv_mean: float
    npv_std: float
    npv_percentiles: PercentileResults
    npv_histogram: HistogramData

    # IRR
    irr_mean: Optional[float] = None
    irr_std: Optional[float] = None
    irr_percentiles: Optional[PercentileResults] = None
    irr_valid_pct: Optional[float] = None

    # Payback
    breakeven: BreakevenInfo

    # Risk
    risk_metrics: RiskMetrics

    # Revenue decomposition (mean across scenarios)
    mean_arbitrage_revenue_pln: float
    mean_capacity_fee_savings_pln: float
    mean_autoconsumption_savings_pln: float
    mean_total_annual_revenue_pln: float

    # Degradation
    mean_eol_year: Optional[float] = None
    mean_annual_cycles: Optional[float] = None

    # Recommendation
    recommendation: str = Field("", description="Polish-language recommendation")

    # Optional full distributions
    npv_distribution: Optional[List[float]] = None
    irr_distribution: Optional[List[float]] = None
    yearly_cashflows_mean: Optional[List[float]] = None
    yearly_cashflows_p10: Optional[List[float]] = None
    yearly_cashflows_p90: Optional[List[float]] = None


class SizeComparison(BaseModel):
    """Cross-size comparison heatmap data."""
    sizes: List[str]
    prob_positive_npv: List[float]
    npv_p50: List[float]
    npv_p10: List[float]
    recommendation_label: str
    recommendation_reason: str
    optimal_size_index: int


class TornadoBar(BaseModel):
    variable: str
    label_pl: str
    npv_low: float   # NPV when variable is at -1σ
    npv_high: float  # NPV when variable is at +1σ
    impact: float    # |high - low|


# ---------------------------------------------------------------------------
# Main result
# ---------------------------------------------------------------------------

class MCBessResult(BaseModel):
    """Full Monte Carlo BESS simulation result."""

    # Metadata
    simulation_mode: SimulationMode
    convergence: ConvergenceInfo
    computation_time_ms: float
    n_battery_sizes: int

    # Per-size results
    size_results: List[SizeResult]

    # Cross-size comparison
    size_comparison: SizeComparison

    # Sensitivity (tornado)
    tornado: List[TornadoBar]

    # Insights (Polish)
    insights: List[str]

    # Input echo
    analysis_years: int
    discount_rate: float
    start_date: str


# ---------------------------------------------------------------------------
# Job status (for async polling)
# ---------------------------------------------------------------------------

class MCBessJobStatus(BaseModel):
    job_id: str
    state: JobState
    progress_pct: float = Field(0.0, ge=0, le=100)
    iterations_done: int = 0
    iterations_target: int = 0
    convergence_pct: Optional[float] = None
    message: str = ""
    partial_results: Optional[MCBessResult] = None
    result: Optional[MCBessResult] = None
    error: Optional[str] = None
    elapsed_ms: float = 0
