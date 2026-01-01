"""
Portfolio Aggregation Helper (v2.3.0)

SSoT for aggregating multiple sizing runs into a portfolio summary.

Features:
- Sum aggregations (total NPV, total savings, total CAPEX)
- Weighted payback calculation (CAPEX-weighted, or simple average if CAPEX=0)
- Mixed assumptions detection
- Top items by NPV extraction
- Deterministic sorting and tie-breaking

Usage:
    from portfolio_agg import summarize_items

    items = [PortfolioItemSummary(...), ...]
    summary = summarize_items(items)
"""

from typing import List, Optional
from models import PortfolioItemSummary, PortfolioSummary


def summarize_items(items: List[PortfolioItemSummary]) -> PortfolioSummary:
    """
    Aggregate a list of portfolio item summaries into a portfolio summary.

    Args:
        items: List of PortfolioItemSummary objects

    Returns:
        PortfolioSummary with aggregated KPIs and metadata

    Determinism:
        - Items are processed in order provided
        - Top items sorted by NPV desc, then by run_id asc for tie-breaking
        - Versions/modes lists are sorted alphabetically for consistency
    """
    if not items:
        return PortfolioSummary(
            items_total=0,
            items_ok=0,
            items_error=0,
            mixed_assumptions=False,
            assumptions_versions=[],
            schema_versions=[],
            pricing_modes=[],
            total_npv_pln=0.0,
            total_net_savings_pln=0.0,
            total_capex_pln=0.0,
            weighted_payback_years=None,
            avg_irr_pct=None,
            top_items_by_npv=[],
        )

    # Separate OK and error items
    ok_items = [item for item in items if item.status == "ok"]
    error_items = [item for item in items if item.status != "ok"]

    # Collect unique versions/modes (sorted for determinism)
    assumptions_versions = sorted(set(
        item.assumptions_version for item in ok_items
        if item.assumptions_version is not None
    ))
    schema_versions = sorted(set(
        item.schema_version for item in ok_items
        if item.schema_version is not None
    ))
    pricing_modes = sorted(set(
        item.pricing_mode for item in ok_items
        if item.pricing_mode is not None
    ))

    # Detect mixed assumptions
    mixed_assumptions = len(assumptions_versions) > 1

    # Sum aggregations
    total_npv_pln = sum(item.npv_pln for item in ok_items)
    total_net_savings_pln = sum(item.net_savings_pln for item in ok_items)
    total_capex_pln = sum(item.capex_pln for item in ok_items)

    # Weighted payback calculation
    weighted_payback_years = _calculate_weighted_payback(ok_items, total_capex_pln)

    # Average IRR (only for items with IRR values)
    avg_irr_pct = _calculate_avg_irr(ok_items)

    # Top 5 items by NPV (sorted by NPV desc, then run_id asc for tie-breaking)
    top_items_by_npv = _get_top_items_by_npv(ok_items, limit=5)

    return PortfolioSummary(
        items_total=len(items),
        items_ok=len(ok_items),
        items_error=len(error_items),
        mixed_assumptions=mixed_assumptions,
        assumptions_versions=assumptions_versions,
        schema_versions=schema_versions,
        pricing_modes=pricing_modes,
        total_npv_pln=total_npv_pln,
        total_net_savings_pln=total_net_savings_pln,
        total_capex_pln=total_capex_pln,
        weighted_payback_years=weighted_payback_years,
        avg_irr_pct=avg_irr_pct,
        top_items_by_npv=top_items_by_npv,
    )


def _calculate_weighted_payback(
    items: List[PortfolioItemSummary],
    total_capex_pln: float
) -> Optional[float]:
    """
    Calculate CAPEX-weighted average payback period.

    Args:
        items: List of OK items
        total_capex_pln: Total CAPEX across all items

    Returns:
        Weighted average payback, or simple average if total_capex=0,
        or None if no items have payback values
    """
    items_with_payback = [
        item for item in items
        if item.payback_years is not None
    ]

    if not items_with_payback:
        return None

    if total_capex_pln > 0:
        # CAPEX-weighted average
        weighted_sum = sum(
            item.payback_years * item.capex_pln
            for item in items_with_payback
            if item.payback_years is not None
        )
        capex_sum = sum(item.capex_pln for item in items_with_payback)

        if capex_sum > 0:
            return weighted_sum / capex_sum
        else:
            # Fallback to simple average
            return sum(item.payback_years for item in items_with_payback) / len(items_with_payback)
    else:
        # Simple average if no CAPEX
        return sum(item.payback_years for item in items_with_payback) / len(items_with_payback)


def _calculate_avg_irr(items: List[PortfolioItemSummary]) -> Optional[float]:
    """
    Calculate simple average IRR across items with IRR values.

    Args:
        items: List of OK items

    Returns:
        Average IRR, or None if no items have IRR values
    """
    items_with_irr = [
        item for item in items
        if item.irr_pct is not None
    ]

    if not items_with_irr:
        return None

    return sum(item.irr_pct for item in items_with_irr) / len(items_with_irr)


def _get_top_items_by_npv(
    items: List[PortfolioItemSummary],
    limit: int = 5
) -> List[PortfolioItemSummary]:
    """
    Get top N items sorted by NPV (descending).

    Uses run_id as tie-breaker for deterministic ordering.

    Args:
        items: List of OK items
        limit: Maximum number of items to return

    Returns:
        List of top items sorted by NPV desc, run_id asc
    """
    if not items:
        return []

    # Sort by NPV descending, then by run_id ascending for tie-breaking
    sorted_items = sorted(
        items,
        key=lambda x: (-x.npv_pln, x.run_id)
    )

    return sorted_items[:limit]


def extract_item_summary_from_result(
    run_id: str,
    result: dict,
    label: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> PortfolioItemSummary:
    """
    Extract PortfolioItemSummary from a stored sizing result.

    Args:
        run_id: The run identifier
        result: The stored sizing result dictionary
        label: Optional user-provided label
        tags: Optional user-provided tags

    Returns:
        PortfolioItemSummary with extracted KPIs

    Note:
        This function handles missing fields gracefully, setting defaults
        and marking status as 'error' if critical fields are missing.
    """
    try:
        # Extract recommended variant info
        recommended = result.get("recommended", {})
        recommended_variant = recommended.get("variant_name") or recommended.get("name")

        # Extract KPIs from finance_summary or recommended
        finance_summary = recommended.get("finance_summary", {})

        npv_pln = (
            finance_summary.get("npv_pln") or
            recommended.get("npv_pln") or
            0.0
        )

        payback_years = (
            finance_summary.get("payback_years") or
            recommended.get("payback_years")
        )

        irr_pct = (
            finance_summary.get("irr_pct") or
            recommended.get("irr_pct")
        )

        net_savings_pln = (
            finance_summary.get("net_savings_pln") or
            recommended.get("net_savings_pln") or
            recommended.get("annual_savings_pln") or
            0.0
        )

        # Extract CAPEX - try multiple locations
        capex_pln = (
            finance_summary.get("capex_pln") or
            finance_summary.get("total_capex_pln") or
            recommended.get("capex_pln") or
            result.get("assumptions", {}).get("capex_pln") or
            0.0
        )

        # Extract metadata
        meta = result.get("meta", {})
        assumptions_version = (
            meta.get("assumptions_version") or
            result.get("assumptions_version")
        )
        schema_version = (
            meta.get("schema_version") or
            result.get("schema_version")
        )

        # Extract pricing mode (v2.0+)
        pricing_debug = result.get("pricing_debug", {})
        pricing_mode = pricing_debug.get("pricing_mode")

        # Extract objective used
        objective_used = result.get("objective_used") or meta.get("objective_used")

        return PortfolioItemSummary(
            run_id=run_id,
            label=label,
            tags=tags,
            recommended_variant=recommended_variant,
            objective_used=objective_used,
            npv_pln=float(npv_pln) if npv_pln else 0.0,
            payback_years=float(payback_years) if payback_years else None,
            irr_pct=float(irr_pct) if irr_pct else None,
            net_savings_pln=float(net_savings_pln) if net_savings_pln else 0.0,
            capex_pln=float(capex_pln) if capex_pln else 0.0,
            assumptions_version=assumptions_version,
            schema_version=schema_version,
            pricing_mode=pricing_mode,
            status="ok",
            error_message=None,
        )

    except Exception as e:
        return PortfolioItemSummary(
            run_id=run_id,
            label=label,
            tags=tags,
            npv_pln=0.0,
            net_savings_pln=0.0,
            capex_pln=0.0,
            status="error",
            error_message=str(e),
        )
