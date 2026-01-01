"""
Portfolio API endpoints (v2.3.0).

Provides:
- POST /api/bess-dispatch/portfolio/summary - Aggregate multiple runs into portfolio summary
"""

from typing import Any, Dict, List, Optional
import time

from models import (
    PortfolioRequest,
    PortfolioResponse,
    PortfolioRunsSummary,
    PortfolioItemSummary,
    PortfolioItemError,
)
from portfolio_agg import summarize_items, extract_item_summary_from_result


def compute_portfolio_summary(
    run_ids: List[str],
    labels: Optional[Dict[str, str]],
    tags: Optional[Dict[str, List[str]]],
    get_run_fn,
) -> PortfolioResponse:
    """
    Compute portfolio summary from run IDs.

    Args:
        run_ids: List of run IDs to aggregate
        labels: Optional mapping of run_id -> label
        tags: Optional mapping of run_id -> tags
        get_run_fn: Function to retrieve stored run by ID

    Returns:
        PortfolioResponse with summary, items, and errors
    """
    items: List[PortfolioItemSummary] = []
    errors: List[PortfolioItemError] = []

    for run_id in run_ids:
        label = labels.get(run_id) if labels else None
        run_tags = tags.get(run_id) if tags else None

        try:
            # Get stored run result
            run_data = get_run_fn(run_id)

            if run_data is None:
                errors.append(PortfolioItemError(
                    run_id=run_id,
                    error="Run not found"
                ))
                items.append(PortfolioItemSummary(
                    run_id=run_id,
                    label=label,
                    tags=run_tags,
                    status="error",
                    error_message="Run not found"
                ))
                continue

            # Extract item summary from stored result
            item = extract_item_summary_from_result(
                run_id=run_id,
                result=run_data,
                label=label,
                tags=run_tags,
            )
            items.append(item)

            # If extraction had error, also add to errors list
            if item.status == "error":
                errors.append(PortfolioItemError(
                    run_id=run_id,
                    error=item.error_message or "Unknown error"
                ))

        except Exception as e:
            error_msg = str(e)
            errors.append(PortfolioItemError(
                run_id=run_id,
                error=error_msg
            ))
            items.append(PortfolioItemSummary(
                run_id=run_id,
                label=label,
                tags=run_tags,
                status="error",
                error_message=error_msg
            ))

    # Compute summary from items
    summary = summarize_items(items)

    # Convert top_items_by_npv to list (they're already PortfolioItemSummary objects from mock)
    # In real code, they come from the same items list

    return PortfolioResponse(
        summary=summary,
        items=items,
        errors=errors,
    )
