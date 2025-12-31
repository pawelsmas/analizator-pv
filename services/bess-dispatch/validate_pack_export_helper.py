"""
Validate-pack export helper for v1.7.0.

Provides CSV and ZIP export for validation pack results.
"""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List


def export_validate_pack_to_csv(result: Dict[str, Any]) -> str:
    """
    Export validate-pack result to CSV format.

    Creates a summary CSV with one row per scenario showing:
    - scenario name
    - pass/fail status
    - mismatch count
    - error message (if any)
    - failed fields (comma-separated)

    Args:
        result: Validate-pack job result

    Returns:
        CSV string
    """
    scenarios = result.get("scenarios", [])

    if not scenarios:
        return "scenario,pass,mismatch_count,error,failed_fields\n"

    columns = [
        "scenario",
        "pass",
        "mismatch_count",
        "error",
        "failed_fields",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for scenario in scenarios:
        diffs = scenario.get("diffs", [])
        failed_fields = [d.get("field", "") for d in diffs if not d.get("pass", True)]

        row = {
            "scenario": scenario.get("name", ""),
            "pass": scenario.get("pass", False),
            "mismatch_count": scenario.get("mismatch_count", 0),
            "error": scenario.get("error", ""),
            "failed_fields": ",".join(failed_fields),
        }
        writer.writerow(row)

    return output.getvalue()


def export_validate_pack_diffs_to_csv(result: Dict[str, Any]) -> str:
    """
    Export validate-pack diffs to CSV format.

    Creates a detailed CSV with one row per field diff showing:
    - scenario name
    - field name
    - expected value
    - actual value
    - absolute diff
    - relative diff
    - tolerance (abs/rel)
    - pass/fail

    Args:
        result: Validate-pack job result

    Returns:
        CSV string
    """
    scenarios = result.get("scenarios", [])

    columns = [
        "scenario",
        "field",
        "expected",
        "actual",
        "abs_diff",
        "rel_diff",
        "tolerance_abs",
        "tolerance_rel",
        "pass",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for scenario in scenarios:
        scenario_name = scenario.get("name", "")
        diffs = scenario.get("diffs", [])

        for diff in diffs:
            row = {
                "scenario": scenario_name,
                "field": diff.get("field", ""),
                "expected": diff.get("expected"),
                "actual": diff.get("actual"),
                "abs_diff": diff.get("abs_diff"),
                "rel_diff": diff.get("rel_diff"),
                "tolerance_abs": diff.get("tolerance_abs"),
                "tolerance_rel": diff.get("tolerance_rel"),
                "pass": diff.get("pass", True),
            }
            writer.writerow(row)

    return output.getvalue()


def export_validate_pack_to_json(result: Dict[str, Any], job_id: str) -> str:
    """
    Export validate-pack result to JSON format.

    Args:
        result: Validate-pack job result
        job_id: Job ID

    Returns:
        JSON string
    """
    export_data = {
        "job_id": job_id,
        "pack": result.get("pack", ""),
        "pass": result.get("pass", False),
        "summary": result.get("summary", {}),
        "scenarios": result.get("scenarios", []),
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    return json.dumps(export_data, indent=2, ensure_ascii=False)


def export_validate_pack_to_zip(result: Dict[str, Any], job_id: str) -> bytes:
    """
    Export validate-pack result to ZIP archive.

    Contains:
    - summary.csv: High-level pass/fail per scenario
    - diffs.csv: Detailed field-by-field diffs
    - result.json: Full JSON export
    - metadata.json: Export metadata

    Args:
        result: Validate-pack job result
        job_id: Job ID

    Returns:
        ZIP file bytes
    """
    pack_name = result.get("pack", "pack")

    # Generate filename prefix
    prefix = f"validate_{pack_name}_{job_id[:8]}"

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add summary CSV
        summary_csv = export_validate_pack_to_csv(result)
        zf.writestr(f"{prefix}_summary.csv", summary_csv)

        # Add diffs CSV
        diffs_csv = export_validate_pack_diffs_to_csv(result)
        zf.writestr(f"{prefix}_diffs.csv", diffs_csv)

        # Add JSON export
        json_content = export_validate_pack_to_json(result, job_id)
        zf.writestr(f"{prefix}_result.json", json_content)

        # Add metadata
        summary = result.get("summary", {})
        metadata = {
            "job_id": job_id,
            "pack": pack_name,
            "pass": result.get("pass", False),
            "total_scenarios": summary.get("total", 0),
            "passed_scenarios": summary.get("pass", 0),
            "failed_scenarios": summary.get("fail", 0),
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": [
                f"{prefix}_summary.csv",
                f"{prefix}_diffs.csv",
                f"{prefix}_result.json",
            ],
        }
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))

    return zip_buffer.getvalue()
