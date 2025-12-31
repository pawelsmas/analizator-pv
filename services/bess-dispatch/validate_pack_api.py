"""
Validation Packs API endpoints (v1.7.0).

Provides:
- GET /api/bess-dispatch/validation/packs - List available packs
- POST /api/bess-dispatch/jobs/validate-pack - Create validate-pack job
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from validate_pack import (
    list_packs as list_pack_names,
    load_pack,
    run_validate_pack,
    compute_ledger_diffs,  # v1.9.0
    SCENARIOS_ROOT,
    PACKS_DIR,
)


# =============================================================================
# Models
# =============================================================================

class PackListResponse(BaseModel):
    """Response for GET /validation/packs"""
    packs: List[str] = Field(..., description="List of available pack names")


class CreateValidatePackJobRequest(BaseModel):
    """Request for POST /jobs/validate-pack"""
    pack: str = Field(..., description="Pack name to validate")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key for deduplication")
    wait: bool = Field(False, description="If true, process inline and return completed job")
    strict: bool = Field(True, description="If true, fail on any validation errors")


class ValidatePackJobResponse(BaseModel):
    """Response for validate-pack job"""
    job_id: str
    type: str = "validate_pack"
    pack: str
    status: str
    items_total: int
    items_done: int = 0
    error_count: int = 0
    result: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# =============================================================================
# Helpers
# =============================================================================

def validate_one_scenario_sync(
    request: Dict[str, Any],
    expected_kpis: Dict[str, Any],
    tolerances: Dict[str, Any],
    run_sizing_fn,
    extract_kpis_fn,
    kpi_to_dict_fn,
    compute_diffs_fn,
    tolerance_config_class,
) -> Dict[str, Any]:
    """
    Validate a single scenario (adapter for run_validate_pack).

    This runs sizing and compares against expected KPIs.
    Designed to be called from sync context.
    """
    # Build tolerances config
    tol_config = tolerance_config_class(
        default_abs=tolerances.get("default_abs", 1.0),
        default_rel=tolerances.get("default_rel", 0.001),
        per_field_abs=tolerances.get("per_field_abs", {}),
        per_field_rel=tolerances.get("per_field_rel", {}),
    )

    # Run sizing
    try:
        sizing_response = run_sizing_fn(request)
    except Exception as e:
        return {"passed": False, "error": f"Sizing failed: {e}", "diffs": []}

    # Convert to dict
    if hasattr(sizing_response, 'model_dump'):
        response_dict = sizing_response.model_dump(mode="json")
    else:
        response_dict = sizing_response

    # Extract run_id and request_hash
    run_id = response_dict.get("cache_info", {}).get("run_id")
    request_hash = response_dict.get("cache_info", {}).get("request_hash")

    # Extract actual KPIs
    actual_kpis = extract_kpis_fn(response_dict)
    actual_kpis_dict = kpi_to_dict_fn(actual_kpis)

    # Compute diffs
    diffs = compute_diffs_fn(expected_kpis, actual_kpis_dict, tol_config)

    # Determine pass/fail
    failed_fields = [d.field for d in diffs if not d.pass_]
    passed = len(failed_fields) == 0

    # Convert diffs to dicts
    diffs_as_dicts = [
        {
            "field": d.field,
            "expected": d.expected,
            "actual": d.actual,
            "abs_diff": d.abs_diff,
            "rel_diff": d.rel_diff,
            "tolerance_abs": d.tolerance_abs,
            "tolerance_rel": d.tolerance_rel,
            "pass": d.pass_,
        }
        for d in diffs
    ]

    # Compute ledger_diffs if money_ledger is present (v1.9.0)
    ledger_diffs = []
    expected_ledger = expected_kpis.get("money_ledger")
    # Get actual money_ledger from recommended variant
    variants = response_dict.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), None)
    actual_ledger = recommended.get("money_ledger") if recommended else None

    if expected_ledger and actual_ledger:
        ledger_diffs = compute_ledger_diffs(expected_ledger, actual_ledger)

    return {
        "passed": passed,
        "diffs": diffs_as_dicts,
        "ledger_diffs": ledger_diffs,  # v1.9.0
        "run_id": run_id,
        "request_hash": request_hash,
    }


def process_validate_pack_job(
    pack_name: str,
    validate_one_fn,
    scenarios_root: Path = SCENARIOS_ROOT,
    packs_dir: Path = PACKS_DIR,
) -> Dict[str, Any]:
    """Process a validate-pack job."""
    result = run_validate_pack(
        pack_name=pack_name,
        validate_one_fn=validate_one_fn,
        scenarios_root=scenarios_root,
        packs_dir=packs_dir,
    )
    return result
