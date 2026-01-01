"""
Job handlers for async job execution (v3.4.0 PR3).

Implements execute_job handlers for:
- report_run: Generate PDF/XLSX report from a run
- report_portfolio: Generate portfolio report
- sizing_batch: Batch sizing runs (stub, future PR)
- validate_pack: Validate scenario pack (stub, future PR)
"""

import json
import logging
from typing import Any, Dict

from db_models import JobQueue
from job_artifacts import save_artifact
from run_store import get_run_store
from report_data import build_report_data_from_run, ReportOptions
from report_models import ReportProfile
from report_pdf import render_pdf
from report_xlsx import render_xlsx


logger = logging.getLogger("job_handlers")


def handle_report_run(job: JobQueue, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle report_run job: Generate PDF and XLSX from a run.

    Payload:
        run_id: str - Run ID to generate report for
        profile: str (optional) - "executive" or "engineering" (default: executive)
        formats: list (optional) - ["pdf", "xlsx"] (default: ["pdf"])

    Produces artifacts:
        report.pdf - PDF report
        report.xlsx - Excel report (if requested)

    Returns:
        success: True
        result: {"artifacts": ["report.pdf", ...], "run_id": "..."}
    """
    run_id = payload.get("run_id")
    if not run_id:
        return {
            "success": False,
            "error_code": "MISSING_RUN_ID",
            "error_detail": "run_id is required in payload",
        }

    # Get profile
    profile_str = payload.get("profile", "executive")
    try:
        profile = ReportProfile(profile_str)
    except ValueError:
        profile = ReportProfile.EXECUTIVE

    # Get formats
    formats = payload.get("formats", ["pdf"])
    if not formats:
        formats = ["pdf"]

    # Load run from store
    run_store = get_run_store()
    run_record = run_store.get(run_id)

    if not run_record:
        return {
            "success": False,
            "error_code": "RUN_NOT_FOUND",
            "error_detail": f"Run not found: {run_id}",
        }

    # Build report data
    options = ReportOptions(profile=profile)
    report_data = build_report_data_from_run(run_record, options)

    artifacts = []

    # Generate PDF
    if "pdf" in formats:
        try:
            pdf_bytes = render_pdf(report_data)
            save_artifact(job.id, "report.pdf", pdf_bytes, "application/pdf")
            artifacts.append("report.pdf")
            logger.info(f"Job {job.id}: Generated report.pdf ({len(pdf_bytes)} bytes)")
        except Exception as e:
            logger.exception(f"Job {job.id}: PDF generation failed: {e}")
            return {
                "success": False,
                "error_code": "PDF_GENERATION_FAILED",
                "error_detail": str(e),
            }

    # Generate XLSX
    if "xlsx" in formats:
        try:
            xlsx_bytes = render_xlsx(report_data)
            save_artifact(job.id, "report.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            artifacts.append("report.xlsx")
            logger.info(f"Job {job.id}: Generated report.xlsx ({len(xlsx_bytes)} bytes)")
        except Exception as e:
            logger.exception(f"Job {job.id}: XLSX generation failed: {e}")
            return {
                "success": False,
                "error_code": "XLSX_GENERATION_FAILED",
                "error_detail": str(e),
            }

    return {
        "success": True,
        "result": {
            "run_id": run_id,
            "artifacts": artifacts,
            "profile": profile.value,
        },
    }


def handle_report_portfolio(job: JobQueue, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle report_portfolio job: Generate portfolio report from multiple runs.

    Payload:
        run_ids: list[str] - Run IDs to include in portfolio
        formats: list (optional) - ["pdf", "xlsx"] (default: ["pdf"])

    Produces artifacts:
        portfolio_report.pdf - Portfolio PDF report
        portfolio_report.xlsx - Portfolio Excel (if requested)

    Returns:
        success: True
        result: {"artifacts": [...], "run_count": N}
    """
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        return {
            "success": False,
            "error_code": "MISSING_RUN_IDS",
            "error_detail": "run_ids is required in payload",
        }

    formats = payload.get("formats", ["pdf"])
    if not formats:
        formats = ["pdf"]

    # Load runs
    run_store = get_run_store()
    runs = []
    for run_id in run_ids:
        run_record = run_store.get(run_id)
        if run_record:
            runs.append(run_record)

    if not runs:
        return {
            "success": False,
            "error_code": "NO_RUNS_FOUND",
            "error_detail": f"No runs found for IDs: {run_ids}",
        }

    artifacts = []

    # Generate portfolio report
    # For now, generate a simple JSON summary
    # Full PDF/XLSX can be added using portfolio_report_helper
    try:
        summary = {
            "run_count": len(runs),
            "run_ids": [r.get("meta", {}).get("run_id", "unknown") for r in runs],
            "total_npv": sum(
                r.get("response", {}).get("recommended", {}).get("npv_pln", 0)
                for r in runs
            ),
        }

        # Save JSON summary
        json_bytes = json.dumps(summary, indent=2).encode("utf-8")
        save_artifact(job.id, "portfolio_summary.json", json_bytes, "application/json")
        artifacts.append("portfolio_summary.json")
        logger.info(f"Job {job.id}: Generated portfolio_summary.json")

    except Exception as e:
        logger.exception(f"Job {job.id}: Portfolio generation failed: {e}")
        return {
            "success": False,
            "error_code": "PORTFOLIO_GENERATION_FAILED",
            "error_detail": str(e),
        }

    return {
        "success": True,
        "result": {
            "run_count": len(runs),
            "artifacts": artifacts,
        },
    }


def handle_sizing_batch(job: JobQueue, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle sizing_batch job: Run batch sizing operations.

    Stub implementation - will be expanded in future PRs.
    """
    return {
        "success": False,
        "error_code": "NOT_IMPLEMENTED",
        "error_detail": "sizing_batch handler not yet implemented",
    }


def handle_validate_pack(job: JobQueue, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle validate_pack job: Validate scenario pack.

    Stub implementation - will be expanded in future PRs.
    """
    return {
        "success": False,
        "error_code": "NOT_IMPLEMENTED",
        "error_detail": "validate_pack handler not yet implemented",
    }


# Handler registry
JOB_HANDLERS = {
    "report_run": handle_report_run,
    "report_portfolio": handle_report_portfolio,
    "sizing_batch": handle_sizing_batch,
    "validate_pack": handle_validate_pack,
}


def execute_job(job: JobQueue) -> Dict[str, Any]:
    """
    Execute a job based on its kind.

    Args:
        job: The JobQueue record to execute

    Returns:
        Dict with keys:
        - success: bool
        - result: Optional dict to store in result_json
        - error_code: Optional error code
        - error_detail: Optional error message
    """
    kind = job.kind
    logger.info(f"Executing job {job.id} of kind '{kind}'")

    # Parse payload
    payload = {}
    if job.payload_json:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            return {
                "success": False,
                "result": None,
                "error_code": "INVALID_PAYLOAD",
                "error_detail": "Failed to parse payload JSON",
            }

    # Get handler
    handler = JOB_HANDLERS.get(kind)
    if not handler:
        return {
            "success": False,
            "result": None,
            "error_code": "UNKNOWN_JOB_KIND",
            "error_detail": f"Unknown job kind: {kind}",
        }

    # Execute handler
    try:
        result = handler(job, payload)
        return result
    except Exception as e:
        logger.exception(f"Job {job.id}: Handler failed: {e}")
        return {
            "success": False,
            "result": None,
            "error_code": "HANDLER_EXCEPTION",
            "error_detail": str(e),
        }
