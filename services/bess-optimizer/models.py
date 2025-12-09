"""
BESS Optimizer Service - Pydantic Models
LP/MIP optimization using PyPSA + HiGHS for zero-export PV+BESS systems
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum


class SolverType(str, Enum):
    HIGHS = "highs"
    GLPK = "glpk"
    CBC = "cbc"


class ObjectiveType(str, Enum):
    NPV = "npv"
    PAYBACK = "payback"
    AUTOCONSUMPTION = "autoconsumption"


class TimeResolution(str, Enum):
    HOURLY = "hourly"
    QUARTER_HOURLY = "15min"


class BessOptimizationRequest(BaseModel):
    """Request model for BESS optimization"""

    # Time series data (8760 hours or 35040 quarter-hours)
    pv_generation_kwh: List[float] = Field(..., description="PV generation profile [kWh per timestep]")
    load_kwh: List[float] = Field(..., description="Load profile [kWh per timestep]")

    # PV system info
    pv_capacity_kwp: float = Field(..., gt=0, description="PV capacity [kWp]")

    # BESS sizing constraints
    min_power_kw: float = Field(default=50, ge=0, description="Minimum BESS power [kW]")
    max_power_kw: float = Field(default=10000, gt=0, description="Maximum BESS power [kW]")
    min_energy_kwh: float = Field(default=100, ge=0, description="Minimum BESS energy [kWh]")
    max_energy_kwh: float = Field(default=50000, gt=0, description="Maximum BESS energy [kWh]")
    duration_min_h: float = Field(default=1, ge=0.5, description="Minimum duration E/P [hours]")
    duration_max_h: float = Field(default=4, le=8, description="Maximum duration E/P [hours]")

    # BESS technical parameters
    roundtrip_efficiency: float = Field(default=0.90, ge=0.7, le=1.0, description="Round-trip efficiency")
    soc_min: float = Field(default=0.10, ge=0, le=0.5, description="Minimum SOC")
    soc_max: float = Field(default=0.90, ge=0.5, le=1.0, description="Maximum SOC")

    # BESS economic parameters
    capex_per_kwh: float = Field(default=1500, gt=0, description="CAPEX per kWh [PLN/kWh]")
    capex_per_kw: float = Field(default=300, ge=0, description="CAPEX per kW [PLN/kW]")
    opex_pct_per_year: float = Field(default=1.5, ge=0, description="OPEX as % of CAPEX per year")
    lifetime_years: int = Field(default=15, ge=5, le=30, description="BESS lifetime [years]")

    # Energy pricing
    energy_price_plnmwh: float = Field(default=800, gt=0, description="Energy price [PLN/MWh]")

    # Financial parameters
    discount_rate: float = Field(default=0.07, ge=0, le=0.3, description="Discount rate (e.g., 0.07 = 7%)")
    analysis_period_years: int = Field(default=25, ge=10, le=35, description="Analysis period [years]")

    # Optimization settings
    solver: SolverType = Field(default=SolverType.HIGHS, description="LP/MIP solver")
    objective: ObjectiveType = Field(default=ObjectiveType.NPV, description="Optimization objective")
    time_resolution: TimeResolution = Field(default=TimeResolution.HOURLY, description="Time resolution")
    typical_days: int = Field(default=0, ge=0, le=365, description="Typical days compression (0 = full year)")

    # Zero-export constraint
    zero_export: bool = Field(default=True, description="Enforce zero grid export")
    export_penalty_plnmwh: float = Field(default=1000, ge=0, description="Export penalty [PLN/MWh]")


class BessMonthlyData(BaseModel):
    """Monthly BESS operation data"""
    month: int
    charge_kwh: float
    discharge_kwh: float
    cycles: float
    avg_soc: float
    curtailment_kwh: float


class BessOptimizationResult(BaseModel):
    """Result model for BESS optimization"""

    # Optimal sizing
    optimal_power_kw: float = Field(..., description="Optimal BESS power [kW]")
    optimal_energy_kwh: float = Field(..., description="Optimal BESS energy [kWh]")
    optimal_duration_h: float = Field(..., description="Optimal duration E/P [hours]")

    # Economic results
    bess_capex_pln: float = Field(..., description="BESS CAPEX [PLN]")
    annual_savings_pln: float = Field(..., description="Annual savings from BESS [PLN]")
    npv_bess_pln: float = Field(..., description="NPV of BESS investment [PLN]")
    payback_years: Optional[float] = Field(None, description="Simple payback [years]")
    irr_pct: Optional[float] = Field(None, description="IRR [%]")

    # Energy flows (annual)
    annual_charge_kwh: float = Field(..., description="Annual BESS charge [kWh]")
    annual_discharge_kwh: float = Field(..., description="Annual BESS discharge [kWh]")
    annual_cycles: float = Field(..., description="Annual full cycles")
    annual_curtailment_kwh: float = Field(..., description="Annual curtailment [kWh]")

    # Autoconsumption improvement
    autoconsumption_without_bess_pct: float = Field(..., description="Autoconsumption without BESS [%]")
    autoconsumption_with_bess_pct: float = Field(..., description="Autoconsumption with BESS [%]")

    # Monthly breakdown
    monthly_data: List[BessMonthlyData] = Field(default_factory=list, description="Monthly operation data")

    # SOC histogram (for visualization)
    soc_histogram: List[float] = Field(default_factory=list, description="SOC histogram (10 bins, 0-100%)")

    # Hourly dispatch (optional, for detailed analysis)
    hourly_soc: Optional[List[float]] = Field(None, description="Hourly SOC profile")
    hourly_charge_kw: Optional[List[float]] = Field(None, description="Hourly charge power [kW]")
    hourly_discharge_kw: Optional[List[float]] = Field(None, description="Hourly discharge power [kW]")

    # Optimization metadata
    solver_used: str = Field(..., description="Solver used")
    solve_time_s: float = Field(..., description="Solve time [seconds]")
    status: str = Field(..., description="Optimization status")
    objective_value: float = Field(..., description="Objective function value")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = "ok"
    service: str = "bess-optimizer"
    version: str = "1.0.0"
    solver_available: bool = True
