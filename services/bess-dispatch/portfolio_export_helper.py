"""
Portfolio Export Helper (v2.3.0 PR4).

Provides CSV and ZIP export for portfolio summaries.

Features:
- CSV export with flat portfolio items
- ZIP export with summary + items files
- Works with both /portfolio/summary and /jobs portfolio

Usage:
    from portfolio_export_helper import (
        export_portfolio_to_csv,
        export_portfolio_to_zip,
    )
"""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def export_portfolio_to_csv(
    portfolio_summary: Dict[str, Any],
    portfolio_items: List[Dict[str, Any]],
) -> str:
    """
    Export portfolio items to CSV format.

    Flattens key metrics for spreadsheet analysis.

    Args:
        portfolio_summary: PortfolioRunsSummary as dict
        portfolio_items: List of PortfolioItemSummary as dicts

    Returns:
        CSV string with one row per item
    """
    if not portfolio_items:
        return "run_id,label,status,npv_pln,payback_years,net_savings_pln,capex_pln\n"

    # Define columns for CSV export
    columns = [
        "run_id",
        "label",
        "status",
        "recommended_variant",
        "objective_used",
        "npv_pln",
        "payback_years",
        "irr_pct",
        "net_savings_pln",
        "capex_pln",
        "assumptions_version",
        "schema_version",
        "pricing_mode",
        "tags",
        "error_message",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for item in portfolio_items:
        row = {
            "run_id": item.get("run_id"),
            "label": item.get("label"),
            "status": item.get("status"),
            "recommended_variant": item.get("recommended_variant"),
            "objective_used": item.get("objective_used"),
            "npv_pln": item.get("npv_pln"),
            "payback_years": item.get("payback_years"),
            "irr_pct": item.get("irr_pct"),
            "net_savings_pln": item.get("net_savings_pln"),
            "capex_pln": item.get("capex_pln"),
            "assumptions_version": item.get("assumptions_version"),
            "schema_version": item.get("schema_version"),
            "pricing_mode": item.get("pricing_mode"),
            "tags": ",".join(item.get("tags", []) or []),
            "error_message": item.get("error_message"),
        }
        writer.writerow(row)

    return output.getvalue()


def export_portfolio_summary_to_json(
    portfolio_summary: Dict[str, Any],
    portfolio_items: List[Dict[str, Any]],
    source_id: Optional[str] = None,
    source_type: str = "portfolio",
) -> str:
    """
    Export portfolio summary to JSON format.

    Args:
        portfolio_summary: PortfolioRunsSummary as dict
        portfolio_items: List of PortfolioItemSummary as dicts
        source_id: Optional identifier (job_id or summary_id)
        source_type: Type of source ("job" or "portfolio")

    Returns:
        JSON string
    """
    export_data = {
        "source_type": source_type,
        "source_id": source_id,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": portfolio_summary,
        "items": portfolio_items,
    }

    return json.dumps(export_data, indent=2, ensure_ascii=False)


def export_portfolio_to_zip(
    portfolio_summary: Dict[str, Any],
    portfolio_items: List[Dict[str, Any]],
    source_id: Optional[str] = None,
    source_type: str = "portfolio",
) -> bytes:
    """
    Export portfolio to ZIP archive containing JSON and CSV.

    Args:
        portfolio_summary: PortfolioRunsSummary as dict
        portfolio_items: List of PortfolioItemSummary as dicts
        source_id: Optional identifier (job_id or summary_id)
        source_type: Type of source ("job" or "portfolio")

    Returns:
        ZIP file bytes
    """
    # Generate filename prefix
    prefix = f"{source_type}_{source_id[:8] if source_id else 'export'}"

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add JSON export
        json_content = export_portfolio_summary_to_json(
            portfolio_summary=portfolio_summary,
            portfolio_items=portfolio_items,
            source_id=source_id,
            source_type=source_type,
        )
        zf.writestr(f"{prefix}_portfolio.json", json_content)

        # Add CSV export
        csv_content = export_portfolio_to_csv(
            portfolio_summary=portfolio_summary,
            portfolio_items=portfolio_items,
        )
        zf.writestr(f"{prefix}_items.csv", csv_content)

        # Add summary-only CSV
        summary_csv = export_summary_only_csv(portfolio_summary)
        zf.writestr(f"{prefix}_summary.csv", summary_csv)

        # Add metadata
        metadata = {
            "source_type": source_type,
            "source_id": source_id,
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "items_total": portfolio_summary.get("items_total", 0),
            "items_ok": portfolio_summary.get("items_ok", 0),
            "files": [
                f"{prefix}_portfolio.json",
                f"{prefix}_items.csv",
                f"{prefix}_summary.csv",
            ],
        }
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))

    return zip_buffer.getvalue()


def export_summary_only_csv(portfolio_summary: Dict[str, Any]) -> str:
    """
    Export portfolio summary KPIs to a simple CSV.

    Args:
        portfolio_summary: PortfolioRunsSummary as dict

    Returns:
        CSV string with summary metrics
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Write summary as key-value pairs
    writer.writerow(["metric", "value"])
    writer.writerow(["items_total", portfolio_summary.get("items_total", 0)])
    writer.writerow(["items_ok", portfolio_summary.get("items_ok", 0)])
    writer.writerow(["items_error", portfolio_summary.get("items_error", 0)])
    writer.writerow(["mixed_assumptions", portfolio_summary.get("mixed_assumptions", False)])
    writer.writerow(["total_npv_pln", portfolio_summary.get("total_npv_pln", 0)])
    writer.writerow(["total_net_savings_pln", portfolio_summary.get("total_net_savings_pln", 0)])
    writer.writerow(["total_capex_pln", portfolio_summary.get("total_capex_pln", 0)])
    writer.writerow(["weighted_payback_years", portfolio_summary.get("weighted_payback_years")])
    writer.writerow(["avg_irr_pct", portfolio_summary.get("avg_irr_pct")])

    # Versions and modes
    versions = portfolio_summary.get("assumptions_versions", [])
    writer.writerow(["assumptions_versions", ",".join(versions) if versions else ""])

    return output.getvalue()
