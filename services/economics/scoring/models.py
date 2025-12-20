"""
Scoring Engine Models
=====================
Pydantic models for multi-criteria scoring based on economic KPIs.

Key principles:
1. Scoring uses ACTUAL economic KPIs from economics module (NPV, Payback, LCOE, IRR)
2. Normalization to baseline costs for relative comparisons
3. Piecewise threshold scoring (not min-max across offers)
4. Penalties for oversizing (low auto-consumption, high exported energy)
5. Missing data: exclude metric & rescale weights, show completeness
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from enum import Enum


class ProfileType(str, Enum):
    """Predefined weight profiles"""
    CFO = "cfo"
    ESG = "esg"
    OPERATIONS = "operations"
    CUSTOM = "custom"


class WeightProfile(BaseModel):
    """
    Weight distribution across 4 scoring buckets.
    Weights must sum to 1.0 (100 points total).
    """
    name: ProfileType = ProfileType.CFO
    value_weight: float = Field(default=0.40, ge=0, le=1, description="Value bucket: NPV, Payback, LCOE")
    robustness_weight: float = Field(default=0.30, ge=0, le=1, description="Robustness: IRR, conservative NPV")
    tech_weight: float = Field(default=0.20, ge=0, le=1, description="Tech: auto-consumption, sizing efficiency")
    esg_weight: float = Field(default=0.10, ge=0, le=1, description="ESG: CO2 reduction")

    @property
    def total_weight(self) -> float:
        return self.value_weight + self.robustness_weight + self.tech_weight + self.esg_weight

    def normalize(self) -> "WeightProfile":
        """Normalize weights to sum to 1.0"""
        total = self.total_weight
        if total == 0:
            return WeightProfile()
        return WeightProfile(
            name=self.name,
            value_weight=self.value_weight / total,
            robustness_weight=self.robustness_weight / total,
            tech_weight=self.tech_weight / total,
            esg_weight=self.esg_weight / total,
        )


# Predefined weight profiles
WEIGHT_PROFILES = {
    ProfileType.CFO: WeightProfile(
        name=ProfileType.CFO,
        value_weight=0.50,
        robustness_weight=0.30,
        tech_weight=0.15,
        esg_weight=0.05,
    ),
    ProfileType.ESG: WeightProfile(
        name=ProfileType.ESG,
        value_weight=0.25,
        robustness_weight=0.20,
        tech_weight=0.20,
        esg_weight=0.35,
    ),
    ProfileType.OPERATIONS: WeightProfile(
        name=ProfileType.OPERATIONS,
        value_weight=0.30,
        robustness_weight=0.25,
        tech_weight=0.35,
        esg_weight=0.10,
    ),
    ProfileType.CUSTOM: WeightProfile(
        name=ProfileType.CUSTOM,
        value_weight=0.40,
        robustness_weight=0.30,
        tech_weight=0.20,
        esg_weight=0.10,
    ),
}


class ThresholdRule(BaseModel):
    """
    Single threshold rule for piecewise scoring.
    Points are linearly interpolated between thresholds.

    Example for NPV (in millions PLN):
      thresholds = [0.0, 0.5, 1.0, 2.0, 5.0]
      points =     [0,   5,   10,  15,  20]

    Value 1.5 -> interpolate between (1.0, 10) and (2.0, 15) -> 12.5 points
    """
    thresholds: List[float] = Field(..., min_length=2, description="Threshold values (ascending)")
    points: List[float] = Field(..., min_length=2, description="Points at each threshold")
    higher_is_better: bool = Field(default=True, description="If False, lower values get more points")

    def score(self, value: float) -> float:
        """Calculate points for a given value using linear interpolation"""
        if len(self.thresholds) != len(self.points):
            raise ValueError("thresholds and points must have same length")

        # For metrics where lower is better (Payback, LCOE), invert the logic
        if not self.higher_is_better:
            # Reverse: value below lowest threshold = max points
            if value <= self.thresholds[0]:
                return self.points[-1]  # Best score
            if value >= self.thresholds[-1]:
                return self.points[0]  # Worst score

            # Find bracket and interpolate (reversed)
            for i in range(len(self.thresholds) - 1):
                t_low, t_high = self.thresholds[i], self.thresholds[i + 1]
                if t_low <= value <= t_high:
                    p_high, p_low = self.points[i], self.points[i + 1]  # Reversed
                    ratio = (value - t_low) / (t_high - t_low) if t_high != t_low else 0
                    return p_high - ratio * (p_high - p_low)
            return self.points[0]

        # Standard: higher value = more points
        if value <= self.thresholds[0]:
            return self.points[0]
        if value >= self.thresholds[-1]:
            return self.points[-1]

        for i in range(len(self.thresholds) - 1):
            t_low, t_high = self.thresholds[i], self.thresholds[i + 1]
            if t_low <= value <= t_high:
                p_low, p_high = self.points[i], self.points[i + 1]
                ratio = (value - t_low) / (t_high - t_low) if t_high != t_low else 0
                return p_low + ratio * (p_high - p_low)

        return self.points[-1]


class ThresholdConfig(BaseModel):
    """
    Complete threshold configuration for all KPIs.
    Uses absolute values matching what user sees in Economics module.
    """
    # VALUE bucket (max 40 points)
    # NPV in millions PLN - higher is better
    npv_mln: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[0.0, 0.5, 1.0, 2.0, 5.0],  # mln PLN
            points=[0, 5, 10, 15, 20],
            higher_is_better=True
        ),
        description="NPV in millions PLN"
    )
    # Payback in years - lower is better
    payback_years: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[3, 5, 7, 10, 15],  # years
            points=[20, 15, 10, 5, 0],  # reversed: 3y = 20pts, 15y = 0pts
            higher_is_better=False
        ),
        description="Simple payback period in years"
    )

    # ROBUSTNESS bucket (max 30 points)
    # IRR in % - higher is better
    irr_pct: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[0, 5, 10, 15, 20],  # %
            points=[0, 5, 10, 15, 20],
            higher_is_better=True
        ),
        description="Internal Rate of Return %"
    )
    # LCOE in PLN/MWh - lower is better (robustness = cheap energy)
    lcoe_pln_mwh: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[100, 200, 300, 400, 500],  # PLN/MWh
            points=[10, 7.5, 5, 2.5, 0],  # reversed
            higher_is_better=False
        ),
        description="Levelized Cost of Energy PLN/MWh"
    )

    # TECH bucket (max 20 points)
    # Auto-consumption % - higher is better (good sizing)
    auto_consumption_pct: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[0.30, 0.50, 0.70, 0.85, 0.95],
            points=[0, 2.5, 5, 7.5, 10],
            higher_is_better=True
        ),
        description="Self-consumption percentage (0-1)"
    )
    # Coverage % - optimal around 60-80%, penalize both under and over
    coverage_pct: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[0.20, 0.40, 0.60, 0.80, 1.00],
            points=[2, 5, 10, 8, 5],  # Peak at 60-80%
            higher_is_better=True  # Custom handling in engine
        ),
        description="Coverage of annual consumption (0-1)"
    )

    # ESG bucket (max 10 points)
    # CO2 reduction in tonnes/year - higher is better
    co2_reduction_tons: ThresholdRule = Field(
        default=ThresholdRule(
            thresholds=[0, 100, 500, 1000, 2000],  # tonnes/year
            points=[0, 2.5, 5, 7.5, 10],
            higher_is_better=True
        ),
        description="Annual CO2 reduction in tonnes"
    )


class OfferInputs(BaseModel):
    """
    Input data for a single offer/variant to be scored.
    Uses ACTUAL economic KPIs from Economics module.
    """
    offer_id: str = Field(..., description="Unique offer identifier")
    name: str = Field(..., description="Display name")

    # Installation parameters
    capacity_kwp: float = Field(..., gt=0, description="PV capacity in kWp")
    capex_pln: Optional[float] = Field(default=None, description="Total CAPEX in PLN")

    # Economic KPIs from Economics module (REQUIRED)
    npv_pln: float = Field(..., description="Net Present Value in PLN")
    payback_years: float = Field(..., description="Simple payback period in years")
    irr_pct: Optional[float] = Field(default=None, description="Internal Rate of Return in %")
    lcoe_pln_mwh: Optional[float] = Field(default=None, description="Levelized Cost of Energy in PLN/MWh")

    # Production/consumption metrics
    annual_production_kwh: float = Field(..., description="Annual PV production in kWh")
    self_consumed_kwh: float = Field(..., description="Self-consumed energy in kWh")
    exported_kwh: float = Field(default=0, description="Exported/curtailed energy in kWh")
    annual_consumption_kwh: float = Field(..., description="Total annual consumption in kWh")

    # Derived metrics (calculated if not provided)
    auto_consumption_pct: Optional[float] = Field(default=None, description="Self-consumption ratio (0-1)")
    coverage_pct: Optional[float] = Field(default=None, description="Coverage of consumption (0-1)")

    # ESG
    co2_reduction_tons: Optional[float] = Field(default=None, description="Annual CO2 reduction in tonnes")

    # Conservative scenario (optional)
    npv_conservative_pln: Optional[float] = Field(default=None, description="NPV in conservative scenario")

    def get_auto_consumption_pct(self) -> float:
        """Calculate auto-consumption if not provided"""
        if self.auto_consumption_pct is not None:
            return self.auto_consumption_pct
        if self.annual_production_kwh > 0:
            return self.self_consumed_kwh / self.annual_production_kwh
        return 0.0

    def get_coverage_pct(self) -> float:
        """Calculate coverage if not provided"""
        if self.coverage_pct is not None:
            return self.coverage_pct
        if self.annual_consumption_kwh > 0:
            return self.self_consumed_kwh / self.annual_consumption_kwh
        return 0.0


class ScoringParameters(BaseModel):
    """Parameters for scoring calculation"""
    horizon_years: int = Field(
        default=25, ge=5, le=30,
        description="Analysis horizon T (years) - for display only"
    )
    profile: WeightProfile = Field(
        default_factory=lambda: WEIGHT_PROFILES[ProfileType.CFO],
        description="Weight profile for scoring"
    )
    thresholds: ThresholdConfig = Field(
        default_factory=ThresholdConfig,
        description="Threshold configuration for all KPIs"
    )
    # Baseline for relative calculations
    baseline_annual_cost_pln: Optional[float] = Field(
        default=None,
        description="Annual baseline energy cost for relative NPV calculation"
    )


class KPIRaw(BaseModel):
    """Raw KPI values from offer inputs"""
    # Value
    npv_mln: float = 0.0
    payback_years: float = 0.0

    # Robustness
    irr_pct: float = 0.0
    lcoe_pln_mwh: float = 0.0

    # Tech
    auto_consumption_pct: float = 0.0
    coverage_pct: float = 0.0
    exported_pct: float = 0.0  # % of production exported (penalty indicator)

    # ESG
    co2_reduction_tons: float = 0.0


class BucketScores(BaseModel):
    """Scores per bucket (after weighting)"""
    value: float = 0.0  # max ~40 pts weighted
    robustness: float = 0.0  # max ~30 pts
    tech: float = 0.0  # max ~20 pts
    esg: float = 0.0  # max ~10 pts


class PointsBreakdown(BaseModel):
    """Detailed points per KPI (for auditability)"""
    # Value
    npv_pts: float = 0.0
    payback_pts: float = 0.0

    # Robustness
    irr_pts: float = 0.0
    lcoe_pts: float = 0.0

    # Tech
    auto_consumption_pts: float = 0.0
    coverage_pts: float = 0.0

    # ESG
    co2_pts: float = 0.0


class CompletenessInfo(BaseModel):
    """Tracks which KPIs were available for scoring"""
    available_kpis: List[str] = Field(default_factory=list)
    missing_kpis: List[str] = Field(default_factory=list)
    weight_adjustment: float = Field(
        default=1.0,
        description="Factor by which weights were rescaled due to missing data"
    )


class Flag(BaseModel):
    """Warning or info flag for the offer"""
    type: Literal["warning", "info", "success"] = "info"
    code: str
    message: str


class ScoreResult(BaseModel):
    """Complete scoring result for a single offer"""
    offer_id: str
    offer_name: str

    # Final score (0-100)
    total_score: float = Field(ge=0, le=100)
    rank: Optional[int] = None

    # Bucket scores (weighted)
    bucket_scores: BucketScores

    # Raw KPIs (for display)
    kpi_raw: KPIRaw

    # Points breakdown (for auditability)
    points_breakdown: PointsBreakdown

    # Data completeness
    completeness: CompletenessInfo

    # Flags (warnings, info)
    flags: List[Flag] = Field(default_factory=list)

    # Auto-generated reasons
    reasons: List[str] = Field(default_factory=list)


class ScoringRequest(BaseModel):
    """Request to score multiple offers"""
    offers: List[OfferInputs] = Field(..., min_length=1)
    parameters: ScoringParameters = Field(default_factory=ScoringParameters)


class ScoringResponse(BaseModel):
    """Response with scored offers"""
    results: List[ScoreResult]
    rules_used: ThresholdConfig
    profile_used: WeightProfile
    parameters_used: ScoringParameters
    comparison_available: bool = Field(
        default=False,
        description="True if 2+ offers available for comparison"
    )
