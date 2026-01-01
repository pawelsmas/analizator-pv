"""
Ledger Timeseries Helper (v2.0.0 PR3).

Generates per-step cost timeseries from energy flows and prices.

This module is the SINGLE SOURCE OF TRUTH for:
- Computing per-step costs from energy and prices
- Summing per-step costs to match MoneyLedger totals
- Validating ledger timeseries integrity (sum invariants)
"""

import logging
from typing import List, Tuple

from models import (
    LedgerTimeseriesPlnPerStep,
    PriceTimeseriesPlnPerMwh,
    MoneyLedgerTotalsPln,
)

logger = logging.getLogger(__name__)


def generate_ledger_timeseries(
    grid_import_kwh: List[float],
    grid_export_kwh: List[float],
    price_timeseries: PriceTimeseriesPlnPerMwh,
    unserved_load_kwh: List[float] = None,
) -> LedgerTimeseriesPlnPerStep:
    """
    Generate per-step cost timeseries from energy flows and prices.

    Args:
        grid_import_kwh: Grid import energy per step [kWh]
        grid_export_kwh: Grid export energy per step [kWh]
        price_timeseries: Price timeseries with import/export/fees prices
        unserved_load_kwh: Unserved load per step [kWh] (optional)

    Returns:
        LedgerTimeseriesPlnPerStep with costs at each timestep
    """
    n_steps = len(grid_import_kwh)
    step_minutes = price_timeseries.step_minutes

    # Calculate per-step costs
    import_cost_pln = []
    export_revenue_pln = []
    other_fees_pln = []
    unserved_penalty_pln = []
    net_cost_pln = []

    for i in range(n_steps):
        # Import cost: energy_kwh * price_pln_per_mwh / 1000
        import_kwh = grid_import_kwh[i]
        import_price = price_timeseries.import_price_pln_per_mwh[i]
        import_cost = import_kwh * import_price / 1000.0  # Convert MWh to kWh
        import_cost_pln.append(import_cost)

        # Export revenue: energy_kwh * price_pln_per_mwh / 1000
        export_kwh = grid_export_kwh[i]
        export_price = price_timeseries.export_price_pln_per_mwh[i]
        export_rev = export_kwh * export_price / 1000.0
        export_revenue_pln.append(export_rev)

        # Other fees: import_kwh * fees_pln_per_mwh / 1000
        if price_timeseries.other_fees_pln_per_mwh and len(price_timeseries.other_fees_pln_per_mwh) > i:
            fees_price = price_timeseries.other_fees_pln_per_mwh[i]
            fees_cost = import_kwh * fees_price / 1000.0
        else:
            fees_cost = 0.0
        other_fees_pln.append(fees_cost)

        # Unserved penalty: unserved_kwh * penalty_pln_per_kwh
        if unserved_load_kwh and len(unserved_load_kwh) > i:
            unserved_kwh = unserved_load_kwh[i]
            if price_timeseries.unserved_penalty_pln_per_kwh and len(price_timeseries.unserved_penalty_pln_per_kwh) > i:
                penalty_rate = price_timeseries.unserved_penalty_pln_per_kwh[i]
            else:
                penalty_rate = 10.0  # Default penalty rate
            penalty_cost = unserved_kwh * penalty_rate
        else:
            penalty_cost = 0.0
        unserved_penalty_pln.append(penalty_cost)

        # Net cost per step
        net = import_cost + fees_cost + penalty_cost - export_rev
        net_cost_pln.append(net)

    # Create ledger timeseries with calculated sums
    ledger = LedgerTimeseriesPlnPerStep(
        import_cost_pln=import_cost_pln,
        export_revenue_pln=export_revenue_pln,
        other_fees_pln=other_fees_pln,
        unserved_penalty_pln=unserved_penalty_pln,
        net_cost_pln=net_cost_pln,
        step_minutes=step_minutes,
        steps=n_steps,
        sum_import_cost_pln=sum(import_cost_pln),
        sum_export_revenue_pln=sum(export_revenue_pln),
        sum_other_fees_pln=sum(other_fees_pln),
        sum_unserved_penalty_pln=sum(unserved_penalty_pln),
        sum_net_cost_pln=sum(net_cost_pln),
    )

    return ledger


def validate_ledger_vs_money_ledger(
    ledger_ts: LedgerTimeseriesPlnPerStep,
    money_ledger: MoneyLedgerTotalsPln,
    tolerance_pln: float = 1.0,
) -> Tuple[bool, List[str]]:
    """
    Validate that ledger timeseries sums match MoneyLedger totals.

    This is a critical invariant: sum of per-step costs should equal
    the totals in MoneyLedger.

    Args:
        ledger_ts: Ledger timeseries with per-step costs
        money_ledger: MoneyLedger totals to compare against
        tolerance_pln: Tolerance for floating point comparison [PLN]

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []

    # Import cost check
    if abs(ledger_ts.sum_import_cost_pln - money_ledger.import_energy_cost_pln) > tolerance_pln:
        errors.append(
            f"import_cost mismatch: ledger={ledger_ts.sum_import_cost_pln:.2f} "
            f"!= money_ledger={money_ledger.import_energy_cost_pln:.2f}"
        )

    # Export revenue check
    if abs(ledger_ts.sum_export_revenue_pln - money_ledger.export_revenue_pln) > tolerance_pln:
        errors.append(
            f"export_revenue mismatch: ledger={ledger_ts.sum_export_revenue_pln:.2f} "
            f"!= money_ledger={money_ledger.export_revenue_pln:.2f}"
        )

    # Other fees check
    if abs(ledger_ts.sum_other_fees_pln - money_ledger.other_fees_pln) > tolerance_pln:
        errors.append(
            f"other_fees mismatch: ledger={ledger_ts.sum_other_fees_pln:.2f} "
            f"!= money_ledger={money_ledger.other_fees_pln:.2f}"
        )

    # Unserved penalty check
    if abs(ledger_ts.sum_unserved_penalty_pln - money_ledger.unserved_penalty_pln) > tolerance_pln:
        errors.append(
            f"unserved_penalty mismatch: ledger={ledger_ts.sum_unserved_penalty_pln:.2f} "
            f"!= money_ledger={money_ledger.unserved_penalty_pln:.2f}"
        )

    # Net cost vs total_cost check
    expected_net = (
        money_ledger.import_energy_cost_pln +
        money_ledger.other_fees_pln +
        money_ledger.unserved_penalty_pln -
        money_ledger.export_revenue_pln
    )
    if abs(ledger_ts.sum_net_cost_pln - expected_net) > tolerance_pln:
        errors.append(
            f"net_cost mismatch: ledger={ledger_ts.sum_net_cost_pln:.2f} "
            f"!= expected={expected_net:.2f}"
        )

    return len(errors) == 0, errors
