"""
KPI Snapshot extraction and diff engine for validation (v1.4.0).

Provides:
- KpiSnapshot: Pydantic model for key performance indicators
- ToleranceConfig: Configuration for validation tolerances
- KpiDiff: Result of comparing expected vs actual KPI
- extract_kpis_from_sizing_response(): Extract KPIs from sizing response
- compute_kpi_diffs(): Compare expected vs actual with tolerances
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class KpiSnapshot(BaseModel):
    """
    Key Performance Indicators extracted from sizing response.

    All values are from the recommended variant.
    """
    # Core recommendation
    recommended_variant: str = Field(..., description="Recommended variant name (small/medium/large)")
    objective_used: Optional[str] = Field(None, description="Optimization objective used")

    # Financial KPIs (from finance_summary)
    net_savings_pln: float = Field(..., description="Net annual savings [PLN]")
    npv_pln: float = Field(..., description="Net Present Value [PLN]")
    payback_years: float = Field(..., description="Simple payback period [years]")
    irr_pct: Optional[float] = Field(None, description="Internal Rate of Return [%]")

    # Savings breakdown components (SSoT)
    energy_savings_pln: float = Field(0.0, description="Energy savings [PLN]")
    capacity_fee_savings_pln: float = Field(0.0, description="Capacity fee savings [PLN]")
    demand_charge_savings_pln: float = Field(0.0, description="Demand charge savings [PLN]")
    arbitrage_savings_pln: float = Field(0.0, description="Arbitrage savings [PLN]")
    export_revenue_savings_pln: float = Field(0.0, description="Export revenue delta [PLN]")
    degradation_cost_pln: float = Field(0.0, description="Degradation cost [PLN]")
    battery_throughput_mwh: float = Field(0.0, description="Battery throughput [MWh]")
    unserved_load_kwh: float = Field(0.0, description="Unserved load [kWh]")

    # Energy flows (from totals_mwh)
    grid_import_mwh: float = Field(0.0, description="Grid import [MWh]")
    grid_export_mwh: float = Field(0.0, description="Grid export [MWh]")
    pv_curtail_mwh: float = Field(0.0, description="PV curtailment [MWh]")


class ToleranceConfig(BaseModel):
    """
    Configuration for KPI validation tolerances.

    A field passes if: abs_diff <= max(abs_tol, abs(expected) * rel_tol)
    """
    default_abs: float = Field(1.0, description="Default absolute tolerance")
    default_rel: float = Field(0.001, description="Default relative tolerance (0.001 = 0.1%)")
    per_field_abs: Dict[str, float] = Field(default_factory=dict, description="Per-field absolute tolerances")
    per_field_rel: Dict[str, float] = Field(default_factory=dict, description="Per-field relative tolerances")


class KpiDiff(BaseModel):
    """
    Result of comparing a single KPI field.
    """
    model_config = {"populate_by_name": True}

    field: str = Field(..., description="Field name")
    expected: float = Field(..., description="Expected value")
    actual: float = Field(..., description="Actual value")
    abs_diff: float = Field(..., description="Absolute difference")
    rel_diff: Optional[float] = Field(None, description="Relative difference (None if expected=0)")
    abs_tol: float = Field(..., description="Absolute tolerance applied")
    rel_tol: float = Field(..., description="Relative tolerance applied")
    pass_: bool = Field(..., description="Whether this field passes validation", alias="pass")


# -----------------------------------------------------------------------------
# KPI Extraction
# -----------------------------------------------------------------------------

def extract_kpis_from_sizing_response(resp: Dict[str, Any]) -> KpiSnapshot:
    """
    Extract KPI snapshot from sizing response.

    Uses the recommended variant's finance_summary, savings_breakdown,
    and dispatch_summary.energy_flows.totals_mwh.

    Args:
        resp: Full sizing response dict

    Returns:
        KpiSnapshot with extracted values
    """
    # Get recommended variant name
    recommended_variant = resp.get("recommended_variant", "unknown")
    objective_used = resp.get("objective_used")

    # Find the recommended variant in variants array
    variants = resp.get("variants", [])
    variant_data = None
    for v in variants:
        if v.get("variant") == recommended_variant:
            variant_data = v
            break

    if variant_data is None and variants:
        # Fallback to first variant
        variant_data = variants[0]
        recommended_variant = variant_data.get("variant", "unknown")

    if variant_data is None:
        # No variants - return empty snapshot
        return KpiSnapshot(
            recommended_variant="unknown",
            objective_used=objective_used,
            net_savings_pln=0.0,
            npv_pln=0.0,
            payback_years=0.0,
        )

    # Extract finance_summary
    finance = variant_data.get("finance_summary", {})
    npv_pln = finance.get("npv_pln", variant_data.get("npv_pln", 0.0))
    payback_years = finance.get("payback_years", variant_data.get("simple_payback_years", 0.0))
    irr_pct = finance.get("irr_pct")

    # Extract savings_breakdown
    savings = variant_data.get("savings_breakdown", {})
    net_savings_pln = savings.get("net_savings_pln", 0.0)
    energy_savings_pln = savings.get("energy_savings_pln", 0.0)
    capacity_fee_savings_pln = savings.get("capacity_fee_savings_pln", 0.0)
    demand_charge_savings_pln = savings.get("demand_charge_savings_pln", 0.0)
    arbitrage_savings_pln = savings.get("arbitrage_savings_pln", 0.0)
    export_revenue_savings_pln = savings.get("export_revenue_savings_pln", 0.0)
    degradation_cost_pln = savings.get("degradation_cost_pln", 0.0)
    battery_throughput_mwh = savings.get("battery_throughput_mwh", 0.0)

    # Extract energy flows from dispatch_summary
    dispatch = variant_data.get("dispatch_summary", {})
    energy_flows = dispatch.get("energy_flows", {})
    totals = energy_flows.get("totals_mwh", {})

    grid_import_mwh = totals.get("grid_import_mwh", 0.0)
    grid_export_mwh = totals.get("grid_export_mwh", 0.0)
    pv_curtail_mwh = totals.get("pv_curtail_mwh", 0.0)

    # Unserved load from constraint_summary
    constraint_summary = dispatch.get("constraint_summary", {})
    unserved_load_kwh = constraint_summary.get("unserved_load_kwh", 0.0)

    return KpiSnapshot(
        recommended_variant=recommended_variant,
        objective_used=objective_used,
        net_savings_pln=net_savings_pln,
        npv_pln=npv_pln,
        payback_years=payback_years,
        irr_pct=irr_pct,
        energy_savings_pln=energy_savings_pln,
        capacity_fee_savings_pln=capacity_fee_savings_pln,
        demand_charge_savings_pln=demand_charge_savings_pln,
        arbitrage_savings_pln=arbitrage_savings_pln,
        export_revenue_savings_pln=export_revenue_savings_pln,
        degradation_cost_pln=degradation_cost_pln,
        battery_throughput_mwh=battery_throughput_mwh,
        unserved_load_kwh=unserved_load_kwh,
        grid_import_mwh=grid_import_mwh,
        grid_export_mwh=grid_export_mwh,
        pv_curtail_mwh=pv_curtail_mwh,
    )


# -----------------------------------------------------------------------------
# Diff Engine
# -----------------------------------------------------------------------------

def compute_kpi_diffs(
    expected: Dict[str, Any],
    actual: Dict[str, Any],
    tolerances: ToleranceConfig,
) -> List[KpiDiff]:
    """
    Compute differences between expected and actual KPI values.

    A field passes if: abs_diff <= max(abs_tol, abs(expected) * rel_tol)

    Args:
        expected: Dict of expected KPI values (field -> value)
        actual: Dict of actual KPI values (field -> value)
        tolerances: Tolerance configuration

    Returns:
        List of KpiDiff objects, one per field in expected
    """
    diffs: List[KpiDiff] = []

    for field, exp_value in expected.items():
        # Skip non-numeric fields
        if not isinstance(exp_value, (int, float)):
            continue

        exp = float(exp_value)
        act = float(actual.get(field, 0.0))

        # Compute absolute difference
        abs_diff = abs(act - exp)

        # Compute relative difference (None if expected is 0)
        rel_diff: Optional[float] = None
        if exp != 0:
            rel_diff = abs_diff / abs(exp)

        # Get tolerances for this field
        abs_tol = tolerances.per_field_abs.get(field, tolerances.default_abs)
        rel_tol = tolerances.per_field_rel.get(field, tolerances.default_rel)

        # Compute effective tolerance: max(abs_tol, |expected| * rel_tol)
        effective_tol = max(abs_tol, abs(exp) * rel_tol)

        # Determine pass/fail
        pass_ = abs_diff <= effective_tol

        diffs.append(KpiDiff(
            field=field,
            expected=exp,
            actual=act,
            abs_diff=abs_diff,
            rel_diff=rel_diff,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            pass_=pass_,
        ))

    return diffs


def kpi_snapshot_to_dict(snapshot: KpiSnapshot) -> Dict[str, Any]:
    """
    Convert KpiSnapshot to dict for comparison.

    Only includes numeric fields (excludes recommended_variant, objective_used).
    """
    data = snapshot.model_dump()
    # Remove non-numeric fields
    data.pop("recommended_variant", None)
    data.pop("objective_used", None)
    return data
