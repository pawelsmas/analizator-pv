"""
Money Ledger Helper (v1.9.0).

Creates MoneyLedger SSoT from dispatch/sizing economics data.
Provides full cost breakdown for baseline vs project scenarios.
"""

from typing import Optional
from models import (
    MoneyLedger,
    MoneyLedgerTotalsPln,
    SavingsBreakdown,
    EconomicsBreakdown,
)


def compute_money_ledger(
    savings_breakdown: SavingsBreakdown,
    economics_breakdown: Optional[EconomicsBreakdown] = None,
    period_hours: int = 8760,
    annualization_factor: float = 1.0,
) -> MoneyLedger:
    """
    Compute MoneyLedger from savings_breakdown and economics_breakdown.

    The MoneyLedger reconstructs baseline/project costs from the savings_breakdown
    (which contains deltas) and economics_breakdown (which has some absolute values).

    Args:
        savings_breakdown: SavingsBreakdown with delta values and export revenues
        economics_breakdown: EconomicsBreakdown with detailed costs (if available)
        period_hours: Number of hours in analysis period
        annualization_factor: Multiplier to convert period to annual (8760 / period_hours)

    Returns:
        MoneyLedger with baseline, project, and delta costs
    """
    is_full_year = period_hours == 8760

    # If no annualization factor provided, calculate from period_hours
    if annualization_factor == 1.0 and period_hours != 8760:
        annualization_factor = 8760.0 / period_hours

    # Extract baseline and project costs
    # We use economics_breakdown.totals_pln for energy costs and capacity/demand charges
    # We use savings_breakdown for export revenues and penalties

    if economics_breakdown and economics_breakdown.totals_pln:
        totals = economics_breakdown.totals_pln

        # Baseline costs (period)
        baseline_period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=totals.energy_cost_baseline_pln,
            export_revenue_pln=savings_breakdown.baseline_export_revenue_pln,
            other_fees_pln=0.0,  # Included in energy_cost (ToU + other fees)
            capacity_fee_pln=totals.capacity_fee_baseline_pln,
            demand_charge_pln=totals.demand_charge_baseline_pln,
            unserved_penalty_pln=0.0,  # No penalty for baseline
            degradation_cost_pln=0.0,  # No degradation for baseline
        )
        baseline_period.total_cost_pln = baseline_period.calculate_total()

        # Project costs (period)
        project_period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=totals.energy_cost_project_pln,
            export_revenue_pln=savings_breakdown.project_export_revenue_pln,
            other_fees_pln=0.0,  # Included in energy_cost (ToU + other fees)
            capacity_fee_pln=totals.capacity_fee_project_pln,
            demand_charge_pln=totals.demand_charge_project_pln,
            unserved_penalty_pln=abs(savings_breakdown.unserved_load_penalty_pln),
            degradation_cost_pln=abs(savings_breakdown.degradation_cost_pln),
        )
        project_period.total_cost_pln = project_period.calculate_total()

    else:
        # Fallback: reconstruct from savings_breakdown only
        # We have deltas (savings) and can compute approximate baseline/project

        # Export revenues are known directly
        baseline_export = savings_breakdown.baseline_export_revenue_pln
        project_export = savings_breakdown.project_export_revenue_pln

        # Energy savings = baseline_cost - project_cost
        # We only know the delta, so set baseline = energy_savings, project = 0
        # This is approximate but preserves the delta correctly
        energy_savings = savings_breakdown.energy_savings_pln + savings_breakdown.arbitrage_savings_pln

        baseline_period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=energy_savings,  # Approximate: baseline cost = savings (project ~= 0)
            export_revenue_pln=baseline_export,
            other_fees_pln=0.0,
            capacity_fee_pln=savings_breakdown.capacity_fee_savings_pln,  # Baseline fee = savings
            demand_charge_pln=savings_breakdown.demand_charge_savings_pln,  # Baseline charge = savings
            unserved_penalty_pln=0.0,
            degradation_cost_pln=0.0,
        )
        baseline_period.total_cost_pln = baseline_period.calculate_total()

        project_period = MoneyLedgerTotalsPln(
            import_energy_cost_pln=0.0,  # Approximate
            export_revenue_pln=project_export,
            other_fees_pln=0.0,
            capacity_fee_pln=0.0,  # Approximate
            demand_charge_pln=0.0,  # Approximate
            unserved_penalty_pln=abs(savings_breakdown.unserved_load_penalty_pln),
            degradation_cost_pln=abs(savings_breakdown.degradation_cost_pln),
        )
        project_period.total_cost_pln = project_period.calculate_total()

    # Calculate period delta (baseline - project = savings)
    delta_period = MoneyLedgerTotalsPln(
        import_energy_cost_pln=baseline_period.import_energy_cost_pln - project_period.import_energy_cost_pln,
        export_revenue_pln=project_period.export_revenue_pln - baseline_period.export_revenue_pln,
        other_fees_pln=baseline_period.other_fees_pln - project_period.other_fees_pln,
        capacity_fee_pln=baseline_period.capacity_fee_pln - project_period.capacity_fee_pln,
        demand_charge_pln=baseline_period.demand_charge_pln - project_period.demand_charge_pln,
        unserved_penalty_pln=-project_period.unserved_penalty_pln,  # Penalty is a cost to project
        degradation_cost_pln=-project_period.degradation_cost_pln,  # Degradation is a cost to project
    )
    delta_period.total_cost_pln = baseline_period.total_cost_pln - project_period.total_cost_pln

    # Annualize costs
    baseline_annual = _annualize(baseline_period, annualization_factor)
    project_annual = _annualize(project_period, annualization_factor)
    delta_annual = _annualize(delta_period, annualization_factor)

    return MoneyLedger(
        baseline_period=baseline_period,
        project_period=project_period,
        delta_period_pln=delta_period,
        baseline_annual=baseline_annual,
        project_annual=project_annual,
        delta_annual_pln=delta_annual,
        is_full_year=is_full_year,
        period_hours=period_hours,
    )


def _annualize(period: MoneyLedgerTotalsPln, factor: float) -> MoneyLedgerTotalsPln:
    """Annualize period costs by factor."""
    return MoneyLedgerTotalsPln(
        import_energy_cost_pln=period.import_energy_cost_pln * factor,
        export_revenue_pln=period.export_revenue_pln * factor,
        other_fees_pln=period.other_fees_pln * factor,
        capacity_fee_pln=period.capacity_fee_pln * factor,
        demand_charge_pln=period.demand_charge_pln * factor,
        unserved_penalty_pln=period.unserved_penalty_pln * factor,
        degradation_cost_pln=period.degradation_cost_pln * factor,
        total_cost_pln=period.total_cost_pln * factor,
    )
