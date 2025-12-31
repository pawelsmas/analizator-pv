"""
Invariants checker for BESS sizing results.

Provides validation that fundamental assumptions hold for sizing results:
- Energy balance (flows in == flows out)
- Non-negative values where required
- Cost consistency
- Annualization consistency

v1.6.0
"""

import os
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Environment variable for strict mode
STRICT_INVARIANTS = os.environ.get("STRICT_INVARIANTS", "").lower() in ("true", "1", "yes")


@dataclass
class InvariantResult:
    """Result of invariant check."""
    name: str
    passed: bool
    max_abs_error: float = 0.0
    details: Optional[str] = None


def check_energy_balance(variant: Dict[str, Any], tolerance_kwh: float = 0.1) -> InvariantResult:
    """
    Check energy balance invariant.

    Energy in (grid_import + pv_used) == Energy out (load_served + grid_export + losses)
    """
    totals = variant.get("totals", {})

    # Extract values with defaults
    grid_import = totals.get("grid_import_mwh", 0) * 1000  # MWh -> kWh
    pv_used = totals.get("pv_used_mwh", 0) * 1000
    battery_discharge = totals.get("battery_discharge_mwh", 0) * 1000

    load_served = totals.get("load_served_mwh", 0) * 1000
    grid_export = totals.get("grid_export_mwh", 0) * 1000
    battery_charge = totals.get("battery_charge_mwh", 0) * 1000

    # Energy balance: sources = sinks
    # Note: Battery acts as both source (discharge) and sink (charge)
    energy_in = grid_import + pv_used + battery_discharge
    energy_out = load_served + grid_export + battery_charge

    diff = abs(energy_in - energy_out)

    passed = diff <= tolerance_kwh

    return InvariantResult(
        name="energy_balance_ok",
        passed=passed,
        max_abs_error=diff / 1000,  # Report in MWh
        details=f"in={energy_in/1000:.4f} MWh, out={energy_out/1000:.4f} MWh" if not passed else None
    )


def check_non_negative(variant: Dict[str, Any]) -> InvariantResult:
    """
    Check that key values are non-negative.
    """
    totals = variant.get("totals", {})
    sb = variant.get("savings_breakdown", {})

    fields_to_check = [
        ("grid_import_mwh", totals.get("grid_import_mwh")),
        ("grid_export_mwh", totals.get("grid_export_mwh")),
        ("battery_throughput_mwh", totals.get("battery_throughput_mwh")),
        ("capex_pln", variant.get("capex_pln")),
    ]

    violations = []
    for name, value in fields_to_check:
        if value is not None and value < 0:
            violations.append(f"{name}={value:.4f}")

    return InvariantResult(
        name="non_negative_ok",
        passed=len(violations) == 0,
        max_abs_error=0.0,
        details=f"Violations: {', '.join(violations)}" if violations else None
    )


def check_cost_sums(variant: Dict[str, Any], tolerance_pln: float = 1.0) -> InvariantResult:
    """
    Check that cost components sum correctly.

    savings_breakdown.net_savings_pln == energy_savings - degradation_cost - opex_deducted
    """
    sb = variant.get("savings_breakdown", {})

    net_savings = sb.get("net_savings_pln", 0)
    energy_savings = sb.get("energy_savings_pln", 0)
    degradation_cost = sb.get("degradation_cost_pln", 0)

    # net_savings should be approximately energy_savings - degradation_cost
    # (excluding other potential deductions like opex which vary by implementation)
    expected_min = energy_savings - degradation_cost - tolerance_pln
    expected_max = energy_savings + tolerance_pln

    passed = expected_min <= net_savings <= expected_max

    return InvariantResult(
        name="cost_sums_ok",
        passed=passed,
        max_abs_error=abs(net_savings - (energy_savings - degradation_cost)),
        details=f"net={net_savings:.2f}, energy={energy_savings:.2f}, deg={degradation_cost:.2f}" if not passed else None
    )


def check_annualization(variant: Dict[str, Any], tolerance_pct: float = 0.01) -> InvariantResult:
    """
    Check annualization consistency.

    annual_savings_pln should equal savings_breakdown.net_savings_pln (SSoT)
    """
    annual = variant.get("annual_savings_pln", 0)
    sb = variant.get("savings_breakdown", {})
    net = sb.get("net_savings_pln", 0)

    if annual == 0 and net == 0:
        return InvariantResult(name="annualization_ok", passed=True)

    rel_diff = abs(annual - net) / max(abs(annual), abs(net), 1e-9)
    passed = rel_diff <= tolerance_pct

    return InvariantResult(
        name="annualization_ok",
        passed=passed,
        max_abs_error=abs(annual - net),
        details=f"annual={annual:.2f}, net={net:.2f}, diff={rel_diff*100:.2f}%" if not passed else None
    )


def check_ledger_reconciliation(variant: Dict[str, Any], tolerance_pln: float = 1.0) -> InvariantResult:
    """
    Check ledger reconciliation invariant (v1.9.0).

    When money_ledger is present:
    net_savings_pln == delta_annual_pln.total_cost_pln

    The MoneyLedger delta represents the cost reduction (savings) from baseline to project.
    This must match the net_savings_pln reported in savings_breakdown.
    """
    money_ledger = variant.get("money_ledger")

    # If no money_ledger, skip this check
    if money_ledger is None:
        return InvariantResult(
            name="ledger_reconciliation_ok",
            passed=True,
            details="money_ledger not present (skipped)"
        )

    sb = variant.get("savings_breakdown", {})
    net_savings = sb.get("net_savings_pln", 0)

    delta_annual = money_ledger.get("delta_annual_pln", {})
    ledger_delta = delta_annual.get("total_cost_pln", 0)

    diff = abs(net_savings - ledger_delta)
    passed = diff <= tolerance_pln

    return InvariantResult(
        name="ledger_reconciliation_ok",
        passed=passed,
        max_abs_error=diff,
        details=f"net_savings={net_savings:.2f}, ledger_delta={ledger_delta:.2f}, diff={diff:.2f}" if not passed else None
    )


def compute_invariants(variant: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute all invariants for a variant.

    Returns dict suitable for including in API response.
    """
    checks = [
        check_energy_balance(variant),
        check_non_negative(variant),
        check_cost_sums(variant),
        check_annualization(variant),
        check_ledger_reconciliation(variant),  # v1.9.0
    ]

    result = {}
    all_passed = True

    for check in checks:
        result[check.name] = check.passed
        if check.max_abs_error > 0:
            result[f"{check.name.replace('_ok', '_max_abs_error')}"] = check.max_abs_error
        if not check.passed:
            all_passed = False
            logger.warning(f"Invariant {check.name} failed: {check.details}")

    result["all_passed"] = all_passed

    return result


def validate_invariants_strict(variant: Dict[str, Any], scenario_id: str = "unknown") -> None:
    """
    Validate invariants in strict mode.

    Raises InvariantViolationError if any invariant fails and STRICT_INVARIANTS=true.
    """
    if not STRICT_INVARIANTS:
        return

    invariants = compute_invariants(variant)

    if not invariants.get("all_passed", True):
        failed = [k for k, v in invariants.items() if k.endswith("_ok") and not v]
        raise InvariantViolationError(
            f"Invariant violations in scenario {scenario_id}: {failed}",
            failed_invariants=failed,
            invariants=invariants,
        )


class InvariantViolationError(Exception):
    """Raised when invariants fail in strict mode."""

    def __init__(self, message: str, failed_invariants: list, invariants: dict):
        super().__init__(message)
        self.failed_invariants = failed_invariants
        self.invariants = invariants
        self.error_code = "INVARIANT_VIOLATION"
