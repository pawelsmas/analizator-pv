"""
Report ZIP Helper (v2.4.0)

Creates deterministic ZIP bundles for run reports.

ZIP contains:
- report.json: ReportData as JSON
- request.json: Original request
- response_meta.json: Run metadata (run_id, request_hash, etc.)
- README.md: Repro instructions
- WARNINGS.txt: Warnings list (if any)
"""

import json
import zipfile
import io
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from report_data import ReportData, build_report_data_from_run
from report_models import ReportOptions


# Fixed ZIP timestamp for determinism (1980-01-01 00:00:00)
# zipfile requires dates >= 1980
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def build_run_report_zip(
    run_record: Dict[str, Any],
    options: Optional[ReportOptions] = None,
) -> bytes:
    """
    Build a deterministic ZIP bundle for a run report.

    Args:
        run_record: Full run record from RunStore
        options: Report generation options

    Returns:
        ZIP file as bytes
    """
    if options is None:
        options = ReportOptions()

    # Extract report data
    report_data = build_report_data_from_run(run_record, options)

    # Prepare files for ZIP
    files = {}

    # 1. report.json - ReportData as JSON
    files["report.json"] = _serialize_report_data(report_data)

    # 2. request.json - Original request
    request = run_record.get("request", {})
    files["request.json"] = _serialize_json(request)

    # 3. response_meta.json - Run metadata
    response_meta = _build_response_meta(run_record)
    files["response_meta.json"] = _serialize_json(response_meta)

    # 4. README.md - Repro instructions
    files["README.md"] = _build_readme(run_record, report_data)

    # 5. WARNINGS.txt - Only if there are warnings
    if report_data.warnings:
        files["WARNINGS.txt"] = _build_warnings_file(report_data.warnings)

    # Build deterministic ZIP
    return _build_zip(files)


def _serialize_report_data(report_data: ReportData) -> str:
    """Serialize ReportData to JSON string."""
    data = asdict(report_data)
    # Convert options to dict if present
    if data.get("options") and hasattr(report_data.options, "model_dump"):
        data["options"] = report_data.options.model_dump()
    return _serialize_json(data)


def _serialize_json(data: Any) -> str:
    """Serialize data to deterministic JSON string."""
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    )


def _build_response_meta(run_record: Dict[str, Any]) -> Dict[str, Any]:
    """Build response metadata from run record."""
    return {
        "run_id": run_record.get("run_id"),
        "request_hash": run_record.get("request_hash"),
        "created_at": run_record.get("created_at"),
        "cache_hit": run_record.get("cache_hit", False),
        "schema_version": run_record.get("schema_version"),
        "assumptions_version": run_record.get("assumptions_version"),
        "endpoint": run_record.get("endpoint"),
        "status": run_record.get("status"),
        "compute_time_ms": run_record.get("compute_time_ms"),
    }


def _build_readme(run_record: Dict[str, Any], report_data: ReportData) -> str:
    """Build README.md with repro instructions."""
    run_id = run_record.get("run_id", "unknown")
    request_hash = run_record.get("request_hash", "unknown")
    created_at = run_record.get("created_at", "unknown")

    meta = report_data.meta
    branding = report_data.options.branding if report_data.options else None

    title = "BESS Sizing Report"
    if branding and branding.report_title:
        title = branding.report_title

    lines = [
        f"# {title}",
        "",
        "## Report Information",
        "",
        f"- **Run ID**: `{run_id}`",
        f"- **Created**: {created_at}",
        f"- **Schema Version**: {meta.schema_version or 'N/A'}",
        f"- **Assumptions Version**: {meta.assumptions_version or 'N/A'}",
        "",
    ]

    if branding:
        if branding.client_name:
            lines.append(f"- **Client**: {branding.client_name}")
        if branding.site_name:
            lines.append(f"- **Site**: {branding.site_name}")
        if branding.prepared_by:
            lines.append(f"- **Prepared By**: {branding.prepared_by}")
        if branding.prepared_for:
            lines.append(f"- **Prepared For**: {branding.prepared_for}")
        if branding.client_name or branding.site_name:
            lines.append("")

    lines.extend([
        "## Reproduction",
        "",
        "To reproduce this run, use the following curl command:",
        "",
        "```bash",
        "curl -X POST http://localhost:8031/sizing \\",
        "  -H 'Content-Type: application/json' \\",
        "  -d @request.json",
        "```",
        "",
        "## Files in this bundle",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| `report.json` | Report data (extracted SSoT) |",
        "| `request.json` | Original sizing request |",
        "| `response_meta.json` | Run metadata |",
        "| `README.md` | This file |",
    ])

    if report_data.warnings:
        lines.append("| `WARNINGS.txt` | Extraction warnings |")

    lines.extend([
        "",
        "## Related endpoints",
        "",
        f"- Get run: `GET /api/bess-dispatch/runs/{run_id}`",
        f"- Get repro bundle: `GET /runs/{run_id}/repro.zip`",
        f"- Get PDF report: `GET /api/bess-dispatch/runs/{run_id}/report.pdf`",
        f"- Get XLSX report: `GET /api/bess-dispatch/runs/{run_id}/report.xlsx`",
        "",
        "---",
        f"Generated at: {datetime.utcnow().isoformat()}Z",
    ])

    return "\n".join(lines)


def _build_warnings_file(warnings: list) -> str:
    """Build WARNINGS.txt content."""
    lines = [
        "# Report Extraction Warnings",
        "",
        "The following warnings were generated during report extraction:",
        "",
    ]

    for i, warning in enumerate(warnings, 1):
        lines.append(f"{i}. {warning}")

    lines.extend([
        "",
        "These warnings typically indicate missing data in older runs.",
        "Report content may be incomplete for fields mentioned above.",
    ])

    return "\n".join(lines)


def _build_zip(files: Dict[str, str]) -> bytes:
    """
    Build deterministic ZIP from file dict.

    Determinism is achieved by:
    - Sorting files alphabetically
    - Using fixed timestamps
    - Using consistent compression settings
    """
    buffer = io.BytesIO()

    # Sort files alphabetically for determinism
    sorted_files = sorted(files.items(), key=lambda x: x[0])

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in sorted_files:
            # Create ZipInfo with fixed timestamp
            info = zipfile.ZipInfo(filename, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED

            # Write file
            zf.writestr(info, content.encode("utf-8"))

    return buffer.getvalue()
