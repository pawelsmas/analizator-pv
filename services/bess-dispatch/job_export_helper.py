"""
Job export helper for v1.2.0.

Provides CSV and JSON export with per-item enrichment.
"""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def enrich_item_result(
    item_result: Dict[str, Any],
    item_request: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enrich a single batch item result with request metadata.

    Args:
        item_result: The item result from batch sizing
        item_request: The original request for this item

    Returns:
        Enriched item with request_summary and key metrics
    """
    enriched = dict(item_result)

    # Add request summary
    if item_request:
        request_data = item_request.get("request", {})
        enriched["request_summary"] = {
            "mode": request_data.get("mode", "unknown"),
            "load_points": len(request_data.get("load_kw", [])),
            "pv_points": len(request_data.get("pv_generation_kw", [])),
            "energy_price_pln_kwh": request_data.get("energy_price_pln_kwh"),
            "peak_limit_kw": request_data.get("peak_limit_kw"),
        }

    # Extract key metrics for flat export
    if item_result.get("status") == "ok":
        response = item_result.get("response", {})
        recommended = response.get("recommended_variant")
        variants = response.get("variants", [])

        # Find recommended variant data
        recommended_variant = None
        for v in variants:
            if v.get("variant") == recommended:
                recommended_variant = v
                break

        if recommended_variant:
            enriched["recommended_npv_pln"] = recommended_variant.get("npv_pln")
            enriched["recommended_payback_years"] = recommended_variant.get(
                "simple_payback_years"
            )
            enriched["recommended_power_kw"] = recommended_variant.get("power_kw")
            enriched["recommended_energy_kwh"] = recommended_variant.get("energy_kwh")
            enriched["recommended_capex_pln"] = recommended_variant.get("capex_pln")

            savings = recommended_variant.get("savings_breakdown", {})
            enriched["recommended_net_savings_pln"] = savings.get("net_savings_pln")

    return enriched


def build_enriched_results(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build enriched results list from job data.

    Args:
        job: Complete job data with result and request

    Returns:
        List of enriched item results
    """
    result = job.get("result", {})
    request = job.get("request", {})

    items_results = result.get("results", [])
    items_requests = request.get("items", [])

    # Build lookup for requests by item_id
    request_by_id = {
        item.get("item_id"): item for item in items_requests if item.get("item_id")
    }

    enriched_items = []
    for item_result in items_results:
        item_id = item_result.get("item_id")
        item_request = request_by_id.get(item_id, {})
        enriched = enrich_item_result(item_result, item_request)
        enriched_items.append(enriched)

    return enriched_items


def export_job_to_json(job: Dict[str, Any], enriched: bool = True) -> str:
    """
    Export job to JSON format.

    Args:
        job: Complete job data
        enriched: Whether to include enriched item data

    Returns:
        JSON string
    """
    export_data = {
        "job_id": job.get("job_id"),
        "batch_id": job.get("batch_id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "items_total": job.get("items_total"),
        "items_done": job.get("items_done"),
        "error_count": job.get("error_count"),
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    if enriched:
        export_data["items"] = build_enriched_results(job)
    else:
        result = job.get("result", {})
        export_data["items"] = result.get("results", [])

    # Add summary from result
    result = job.get("result", {})
    if result.get("summary"):
        export_data["summary"] = result["summary"]
    if result.get("portfolio_summary"):
        export_data["portfolio_summary"] = result["portfolio_summary"]

    return json.dumps(export_data, indent=2, ensure_ascii=False)


def export_job_to_csv(job: Dict[str, Any]) -> str:
    """
    Export job items to CSV format.

    Flattens key metrics for spreadsheet analysis.

    Args:
        job: Complete job data

    Returns:
        CSV string
    """
    enriched_items = build_enriched_results(job)

    if not enriched_items:
        return "item_id,status,error\n"

    # Define columns for CSV export
    columns = [
        "item_id",
        "status",
        "error",
        "recommended_variant",
        "recommended_npv_pln",
        "recommended_payback_years",
        "recommended_power_kw",
        "recommended_energy_kwh",
        "recommended_capex_pln",
        "recommended_net_savings_pln",
        "mode",
        "load_points",
        "pv_points",
        "energy_price_pln_kwh",
        "peak_limit_kw",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for item in enriched_items:
        row = {
            "item_id": item.get("item_id"),
            "status": item.get("status"),
            "error": item.get("error"),
        }

        # Add recommended variant info
        if item.get("status") == "ok":
            response = item.get("response", {})
            row["recommended_variant"] = response.get("recommended_variant")
            row["recommended_npv_pln"] = item.get("recommended_npv_pln")
            row["recommended_payback_years"] = item.get("recommended_payback_years")
            row["recommended_power_kw"] = item.get("recommended_power_kw")
            row["recommended_energy_kwh"] = item.get("recommended_energy_kwh")
            row["recommended_capex_pln"] = item.get("recommended_capex_pln")
            row["recommended_net_savings_pln"] = item.get("recommended_net_savings_pln")

        # Add request summary
        summary = item.get("request_summary", {})
        row["mode"] = summary.get("mode")
        row["load_points"] = summary.get("load_points")
        row["pv_points"] = summary.get("pv_points")
        row["energy_price_pln_kwh"] = summary.get("energy_price_pln_kwh")
        row["peak_limit_kw"] = summary.get("peak_limit_kw")

        writer.writerow(row)

    return output.getvalue()


def export_job_to_zip(job: Dict[str, Any]) -> bytes:
    """
    Export job to ZIP archive containing JSON and CSV.

    Args:
        job: Complete job data

    Returns:
        ZIP file bytes
    """
    job_id = job.get("job_id", "unknown")
    batch_id = job.get("batch_id", "batch")

    # Generate filename prefix
    prefix = f"{batch_id}_{job_id[:8]}"

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add JSON export
        json_content = export_job_to_json(job, enriched=True)
        zf.writestr(f"{prefix}_results.json", json_content)

        # Add CSV export
        csv_content = export_job_to_csv(job)
        zf.writestr(f"{prefix}_summary.csv", csv_content)

        # Add metadata
        metadata = {
            "job_id": job_id,
            "batch_id": batch_id,
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": [f"{prefix}_results.json", f"{prefix}_summary.csv"],
        }
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))

    return zip_buffer.getvalue()
