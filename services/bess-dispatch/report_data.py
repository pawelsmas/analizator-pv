"""
Report Data SSoT Extractor (v2.4.0)

Extracts ReportData from stored run records.
NO recalculation - pure mapping from saved SSoT outputs.

The extractor reads from RunStore and maps existing fields to ReportData.
Missing fields generate warnings but don't fail extraction.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from report_models import ReportOptions, ReportProfile


# =============================================================================
# ReportData Dataclasses
# =============================================================================

@dataclass
class ReportMeta:
    """Report metadata from run record."""
    run_id: str
    created_at: str
    schema_version: Optional[str] = None
    assumptions_version: Optional[str] = None
    git_sha: Optional[str] = None
    build_time_utc: Optional[str] = None
    pricing_mode: Optional[str] = None
    price_hash: Optional[str] = None
    timezone: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    steps: Optional[int] = None
    step_minutes: Optional[int] = None
    period_hours: Optional[float] = None
    is_full_year: Optional[bool] = None


@dataclass
class ReportRecommended:
    """Recommended variant summary."""
    recommended_variant: Optional[str] = None
    objective_used: Optional[str] = None
    recommended_reason_primary: Optional[str] = None
    recommended_reason_details: Optional[str] = None
    npv_pln: Optional[float] = None
    payback_years: Optional[float] = None
    irr_pct: Optional[float] = None
    net_savings_pln: Optional[float] = None


@dataclass
class ReportMoneyLedgerBucket:
    """Single money ledger bucket (baseline/project/delta)."""
    import_energy_cost_pln: float = 0.0
    export_revenue_pln: float = 0.0
    other_fees_pln: float = 0.0
    capacity_fee_pln: float = 0.0
    demand_charge_pln: float = 0.0
    unserved_penalty_pln: float = 0.0
    degradation_cost_pln: float = 0.0
    total_cost_pln: float = 0.0


@dataclass
class ReportMoneyLedgerAnnual:
    """Annual money ledger with baseline/project/delta."""
    baseline: ReportMoneyLedgerBucket = field(default_factory=ReportMoneyLedgerBucket)
    project: ReportMoneyLedgerBucket = field(default_factory=ReportMoneyLedgerBucket)
    delta: ReportMoneyLedgerBucket = field(default_factory=ReportMoneyLedgerBucket)


@dataclass
class ReportFlowsAnnual:
    """Annual energy flows summary."""
    grid_import_mwh: float = 0.0
    grid_export_mwh: float = 0.0
    pv_curtail_mwh: float = 0.0
    unserved_load_kwh: float = 0.0
    unserved_penalty_pln: float = 0.0


@dataclass
class ReportConstraints:
    """Grid constraints summary."""
    max_import_kw: Optional[float] = None
    max_export_kw: Optional[float] = None
    export_limited_steps: int = 0
    export_limited_mwh: float = 0.0
    import_limited_steps: int = 0
    import_limited_mwh: float = 0.0


@dataclass
class ReportCycleSummary:
    """Battery cycle summary (engineering profile)."""
    efc_total: Optional[float] = None
    cycles_per_day_avg: Optional[float] = None
    cycles_per_day_max: Optional[float] = None
    total_throughput_kwh: Optional[float] = None
    cycle_limit_hit: bool = False


@dataclass
class ReportInvariants:
    """Invariant check results (engineering profile)."""
    all_ok: bool = True
    soc_bounds_ok: bool = True
    power_limits_ok: bool = True
    no_simultaneous_ok: bool = True
    energy_balance_ok: bool = True


@dataclass
class ReportDebugEvents:
    """Debug events summary (engineering profile)."""
    steps: int = 0
    export_limited_steps: int = 0
    export_limited_mwh: float = 0.0
    import_limited_steps: int = 0
    import_limited_mwh: float = 0.0
    pv_curtail_mwh: float = 0.0
    unserved_load_kwh: float = 0.0


@dataclass
class ReportDispatchSummary:
    """Dispatch summary for engineering profile."""
    cycle_summary: Optional[ReportCycleSummary] = None
    invariants: Optional[ReportInvariants] = None
    debug_events: Optional[ReportDebugEvents] = None


@dataclass
class ReportData:
    """
    Complete report data extracted from a run.

    This is the SSoT for report generation.
    All fields are mapped from stored run data - no recalculation.
    """
    meta: ReportMeta
    recommended: ReportRecommended
    money_ledger_annual: ReportMoneyLedgerAnnual
    flows_annual: ReportFlowsAnnual
    constraints: ReportConstraints
    dispatch_summary: Optional[ReportDispatchSummary] = None
    warnings: List[str] = field(default_factory=list)
    options: Optional[ReportOptions] = None


# =============================================================================
# Extractor Function
# =============================================================================

def build_report_data_from_run(
    run_record: Dict[str, Any],
    options: Optional[ReportOptions] = None,
) -> ReportData:
    """
    Build ReportData from a stored run record.

    This function ONLY maps existing SSoT data - no recalculation.
    Missing fields generate warnings but don't fail extraction.

    Args:
        run_record: Full run record from RunStore (contains request, response, meta)
        options: Report generation options

    Returns:
        ReportData with all extracted fields and any warnings
    """
    if options is None:
        options = ReportOptions()

    warnings: List[str] = []

    # Extract run record components
    request = run_record.get("request", {})
    response = run_record.get("response", {})
    run_meta = run_record.get("meta", {}) if "meta" in run_record else run_record

    # Build meta
    meta = _extract_meta(run_record, response, warnings)

    # Build recommended
    recommended = _extract_recommended(response, warnings)

    # Build money ledger
    money_ledger_annual = _extract_money_ledger(response, warnings)

    # Build flows
    flows_annual = _extract_flows(response, warnings)

    # Build constraints
    constraints = _extract_constraints(request, response, warnings)

    # Build dispatch summary (engineering profile only or if present)
    dispatch_summary = None
    if options.profile == ReportProfile.ENGINEERING:
        dispatch_summary = _extract_dispatch_summary(response, warnings)

    return ReportData(
        meta=meta,
        recommended=recommended,
        money_ledger_annual=money_ledger_annual,
        flows_annual=flows_annual,
        constraints=constraints,
        dispatch_summary=dispatch_summary,
        warnings=warnings,
        options=options,
    )


def _extract_meta(
    run_record: Dict[str, Any],
    response: Dict[str, Any],
    warnings: List[str],
) -> ReportMeta:
    """Extract ReportMeta from run record and response."""
    # Run-level meta
    run_id = run_record.get("run_id", "unknown")
    created_at = run_record.get("created_at", datetime.now().isoformat())
    schema_version = run_record.get("schema_version")
    assumptions_version = run_record.get("assumptions_version")

    # Response meta
    resp_meta = response.get("meta", {})
    git_sha = resp_meta.get("git_sha")
    build_time_utc = resp_meta.get("build_time_utc")

    if git_sha is None:
        warnings.append("git_sha not present in run (old run?)")
    if build_time_utc is None:
        warnings.append("build_time_utc not present in run")

    # Period info
    period_info = response.get("period_info", {})
    pricing_debug = response.get("pricing_debug", {})

    pricing_mode = pricing_debug.get("pricing_mode")
    price_hash = pricing_debug.get("price_hash")

    if pricing_mode is None:
        warnings.append("pricing_mode not present (pre-v2.0 run?)")

    return ReportMeta(
        run_id=run_id,
        created_at=created_at,
        schema_version=schema_version,
        assumptions_version=assumptions_version,
        git_sha=git_sha,
        build_time_utc=build_time_utc,
        pricing_mode=pricing_mode,
        price_hash=price_hash,
        timezone=period_info.get("timezone"),
        period_start=period_info.get("start_datetime"),
        period_end=period_info.get("end_datetime"),
        steps=period_info.get("steps"),
        step_minutes=period_info.get("step_minutes"),
        period_hours=period_info.get("period_hours"),
        is_full_year=period_info.get("is_full_year"),
    )


def _extract_recommended(
    response: Dict[str, Any],
    warnings: List[str],
) -> ReportRecommended:
    """Extract recommended variant summary."""
    recommended = response.get("recommended", {})

    if not recommended:
        warnings.append("No recommended variant in response")
        return ReportRecommended()

    # Extract variant name
    variant_name = recommended.get("variant_name") or recommended.get("name")

    # Extract finance summary
    finance = recommended.get("finance_summary", {})

    # NPV/Payback/IRR from finance_summary or recommended
    npv_pln = finance.get("npv_pln") or recommended.get("npv_pln")
    payback_years = finance.get("payback_years") or recommended.get("payback_years")
    irr_pct = finance.get("irr_pct") or recommended.get("irr_pct")

    # Net savings
    net_savings_pln = (
        finance.get("net_savings_pln") or
        recommended.get("net_savings_pln") or
        recommended.get("annual_savings_pln")
    )

    if net_savings_pln is None:
        warnings.append("net_savings_pln not found in recommended variant")

    return ReportRecommended(
        recommended_variant=variant_name,
        objective_used=response.get("objective_used"),
        recommended_reason_primary=recommended.get("recommendation_reason"),
        recommended_reason_details=recommended.get("recommendation_details"),
        npv_pln=npv_pln,
        payback_years=payback_years,
        irr_pct=irr_pct,
        net_savings_pln=net_savings_pln,
    )


def _extract_money_ledger(
    response: Dict[str, Any],
    warnings: List[str],
) -> ReportMoneyLedgerAnnual:
    """Extract MoneyLedger annual buckets."""
    recommended = response.get("recommended", {})
    money_ledger = recommended.get("money_ledger", {})

    if not money_ledger:
        warnings.append("money_ledger not present in recommended variant")
        return ReportMoneyLedgerAnnual()

    # Extract annual buckets
    baseline_annual = money_ledger.get("baseline_annual", {})
    project_annual = money_ledger.get("project_annual", {})
    delta_annual = money_ledger.get("delta_annual_pln", {})

    return ReportMoneyLedgerAnnual(
        baseline=_map_ledger_bucket(baseline_annual),
        project=_map_ledger_bucket(project_annual),
        delta=_map_ledger_bucket(delta_annual),
    )


def _map_ledger_bucket(bucket: Dict[str, Any]) -> ReportMoneyLedgerBucket:
    """Map a money ledger bucket dict to dataclass."""
    return ReportMoneyLedgerBucket(
        import_energy_cost_pln=bucket.get("import_energy_cost_pln", 0.0),
        export_revenue_pln=bucket.get("export_revenue_pln", 0.0),
        other_fees_pln=bucket.get("other_fees_pln", 0.0),
        capacity_fee_pln=bucket.get("capacity_fee_pln", 0.0),
        demand_charge_pln=bucket.get("demand_charge_pln", 0.0),
        unserved_penalty_pln=bucket.get("unserved_penalty_pln", 0.0),
        degradation_cost_pln=bucket.get("degradation_cost_pln", 0.0),
        total_cost_pln=bucket.get("total_cost_pln", 0.0),
    )


def _extract_flows(
    response: Dict[str, Any],
    warnings: List[str],
) -> ReportFlowsAnnual:
    """Extract annual energy flows."""
    recommended = response.get("recommended", {})
    totals = recommended.get("totals", {})

    if not totals:
        warnings.append("totals not present in recommended variant")
        return ReportFlowsAnnual()

    # Extract flows
    # Unserved penalty from money_ledger or savings_breakdown
    money_ledger = recommended.get("money_ledger", {})
    project_annual = money_ledger.get("project_annual", {})
    unserved_penalty = project_annual.get("unserved_penalty_pln", 0.0)

    return ReportFlowsAnnual(
        grid_import_mwh=totals.get("grid_import_mwh", 0.0),
        grid_export_mwh=totals.get("grid_export_mwh", 0.0),
        pv_curtail_mwh=totals.get("pv_curtail_mwh", 0.0),
        unserved_load_kwh=totals.get("unserved_load_kwh", 0.0),
        unserved_penalty_pln=unserved_penalty,
    )


def _extract_constraints(
    request: Dict[str, Any],
    response: Dict[str, Any],
    warnings: List[str],
) -> ReportConstraints:
    """Extract grid constraints summary."""
    # Get constraints from request
    grid_constraints = request.get("grid_constraints", {})
    max_import_kw = grid_constraints.get("max_import_kw")
    max_export_kw = grid_constraints.get("max_export_kw")

    # Get constraint stats from response
    recommended = response.get("recommended", {})
    constraint_summary = recommended.get("constraint_summary", {})
    debug_events = recommended.get("debug_events", {})

    # Prefer debug_events if present (v1.8+)
    if debug_events:
        return ReportConstraints(
            max_import_kw=max_import_kw,
            max_export_kw=max_export_kw,
            export_limited_steps=debug_events.get("export_limited_steps", 0),
            export_limited_mwh=debug_events.get("export_limited_mwh", 0.0),
            import_limited_steps=debug_events.get("import_limited_steps", 0),
            import_limited_mwh=debug_events.get("import_limited_mwh", 0.0),
        )

    # Fallback to constraint_summary
    return ReportConstraints(
        max_import_kw=max_import_kw,
        max_export_kw=max_export_kw,
        export_limited_steps=constraint_summary.get("export_limited_steps", 0),
        export_limited_mwh=constraint_summary.get("export_limited_mwh", 0.0),
        import_limited_steps=constraint_summary.get("import_limited_steps", 0),
        import_limited_mwh=constraint_summary.get("import_limited_mwh", 0.0),
    )


def _extract_dispatch_summary(
    response: Dict[str, Any],
    warnings: List[str],
) -> Optional[ReportDispatchSummary]:
    """Extract dispatch summary for engineering profile."""
    recommended = response.get("recommended", {})

    # Extract cycle summary
    cycle_summary = None
    dispatch_summary = recommended.get("dispatch_summary", {})
    if dispatch_summary:
        cycle_data = dispatch_summary.get("cycle_summary", {})
        if cycle_data:
            cycle_summary = ReportCycleSummary(
                efc_total=cycle_data.get("efc_total"),
                cycles_per_day_avg=cycle_data.get("avg_daily_efc"),
                cycles_per_day_max=cycle_data.get("max_daily_efc"),
                total_throughput_kwh=cycle_data.get("total_throughput_kwh"),
                cycle_limit_hit=cycle_data.get("cycle_limit_hit", False),
            )

    # Extract invariants
    invariants = None
    invariants_data = recommended.get("invariants", {})
    if invariants_data:
        invariants = ReportInvariants(
            all_ok=invariants_data.get("all_ok", True),
            soc_bounds_ok=invariants_data.get("soc_bounds_ok", True),
            power_limits_ok=invariants_data.get("power_limits_ok", True),
            no_simultaneous_ok=invariants_data.get("no_simultaneous_ok", True),
            energy_balance_ok=invariants_data.get("energy_balance_ok", True),
        )

    # Extract debug events
    debug_events = None
    debug_data = recommended.get("debug_events", {})
    if debug_data:
        debug_events = ReportDebugEvents(
            steps=debug_data.get("steps", 0),
            export_limited_steps=debug_data.get("export_limited_steps", 0),
            export_limited_mwh=debug_data.get("export_limited_mwh", 0.0),
            import_limited_steps=debug_data.get("import_limited_steps", 0),
            import_limited_mwh=debug_data.get("import_limited_mwh", 0.0),
            pv_curtail_mwh=debug_data.get("pv_curtail_mwh", 0.0),
            unserved_load_kwh=debug_data.get("unserved_load_kwh", 0.0),
        )

    if cycle_summary is None and invariants is None and debug_events is None:
        warnings.append("No dispatch_summary/invariants/debug_events in response (pre-v2.2 run?)")
        return None

    return ReportDispatchSummary(
        cycle_summary=cycle_summary,
        invariants=invariants,
        debug_events=debug_events,
    )
