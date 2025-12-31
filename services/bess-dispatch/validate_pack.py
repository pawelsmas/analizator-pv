"""
Validate Pack Engine - loader and runner for scenario pack validation.

v1.7.0: Provides functions to load scenario packs and run validation
without HTTP - designed to be used by both CLI scripts and job processor.

Environment variables:
- SCENARIOS_ROOT: Root directory for scenarios (default: docs/scenarios)
- PACKS_DIR: Directory containing pack YAML files (default: docs/scenarios/packs)
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict

import yaml

logger = logging.getLogger(__name__)

# Environment configuration
SCENARIOS_ROOT = Path(os.getenv("SCENARIOS_ROOT", "docs/scenarios"))
PACKS_DIR = Path(os.getenv("PACKS_DIR", "docs/scenarios/packs"))


@dataclass
class ScenarioMismatch:
    """A single field mismatch in validation."""
    field: str
    expected: float
    actual: float
    abs_diff: float
    rel_diff: float
    tolerance_abs: float
    tolerance_rel: float


@dataclass
class LedgerCategoryDiff:
    """Category-level diff between expected and actual money ledger (v1.9.0)."""
    category: str  # e.g., "import_energy_cost_pln", "export_revenue_pln"
    baseline_expected: float
    baseline_actual: float
    project_expected: float
    project_actual: float
    delta_expected: float
    delta_actual: float
    diff_pln: float  # delta_expected - delta_actual


@dataclass
class ScenarioResult:
    """Result of validating a single scenario."""
    name: str
    passed: bool
    mismatch_count: int = 0
    run_id: Optional[str] = None
    request_hash: Optional[str] = None
    top_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    ledger_diffs: List[Dict[str, Any]] = field(default_factory=list)  # v1.9.0
    error: Optional[str] = None


@dataclass
class PackResult:
    """Result of validating a complete pack."""
    pack: str
    passed: bool
    summary: Dict[str, int]
    scenarios: List[ScenarioResult]


def list_packs(packs_dir: Optional[Path] = None) -> List[str]:
    """
    List available scenario packs.

    Args:
        packs_dir: Directory containing pack YAML files (default: PACKS_DIR)

    Returns:
        List of pack names (without .yml extension)
    """
    packs_dir = packs_dir or PACKS_DIR

    if not packs_dir.exists():
        logger.warning(f"Packs directory does not exist: {packs_dir}")
        return []

    packs = []
    for f in packs_dir.glob("*.yml"):
        packs.append(f.stem)
    for f in packs_dir.glob("*.yaml"):
        if f.stem not in packs:
            packs.append(f.stem)

    return sorted(packs)


def load_pack(pack_name: str, packs_dir: Optional[Path] = None) -> List[str]:
    """
    Load a scenario pack and return list of scenario names.

    Args:
        pack_name: Name of the pack (without extension)
        packs_dir: Directory containing pack YAML files (default: PACKS_DIR)

    Returns:
        List of scenario names in order defined in pack

    Raises:
        FileNotFoundError: If pack file doesn't exist
        ValueError: If pack format is invalid
    """
    packs_dir = packs_dir or PACKS_DIR

    # Try .yml first, then .yaml
    pack_file = packs_dir / f"{pack_name}.yml"
    if not pack_file.exists():
        pack_file = packs_dir / f"{pack_name}.yaml"

    if not pack_file.exists():
        raise FileNotFoundError(f"Pack not found: {pack_name}")

    with open(pack_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid pack format: {pack_name}")

    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError(f"Pack 'scenarios' must be a list: {pack_name}")

    return scenarios


def load_scenario_files(
    scenario_name: str,
    scenarios_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load scenario files (request, expected_kpis, tolerances).

    Supports two formats:
    1. New format: docs/scenarios/<name>/request.json, expected_kpis.json, tolerances.json
    2. Legacy format: docs/scenarios/<name>.json (single file with all fields)

    Args:
        scenario_name: Name of the scenario
        scenarios_root: Root directory for scenarios (default: SCENARIOS_ROOT)

    Returns:
        Dict with keys: request, expected_kpis, tolerances

    Raises:
        FileNotFoundError: If scenario files don't exist
    """
    scenarios_root = scenarios_root or SCENARIOS_ROOT

    # Try new directory format first
    scenario_dir = scenarios_root / scenario_name
    if scenario_dir.is_dir():
        return _load_scenario_from_dir(scenario_dir)

    # Fall back to legacy single-file format
    scenario_file = scenarios_root / f"{scenario_name}.json"
    if scenario_file.exists():
        return _load_scenario_from_file(scenario_file, scenarios_root)

    raise FileNotFoundError(f"Scenario not found: {scenario_name}")


def _load_scenario_from_dir(scenario_dir: Path) -> Dict[str, Any]:
    """Load scenario from directory format."""
    request_file = scenario_dir / "request.json"
    expected_file = scenario_dir / "expected_kpis.json"
    tolerances_file = scenario_dir / "tolerances.json"

    if not request_file.exists():
        raise FileNotFoundError(f"request.json not found in {scenario_dir}")
    if not expected_file.exists():
        raise FileNotFoundError(f"expected_kpis.json not found in {scenario_dir}")

    with open(request_file, "r", encoding="utf-8") as f:
        request = json.load(f)

    with open(expected_file, "r", encoding="utf-8") as f:
        expected_kpis = json.load(f)

    tolerances = {}
    if tolerances_file.exists():
        with open(tolerances_file, "r", encoding="utf-8") as f:
            tolerances = json.load(f)

    return {
        "request": request,
        "expected_kpis": expected_kpis,
        "tolerances": tolerances,
    }


def _load_scenario_from_file(scenario_file: Path, scenarios_root: Path) -> Dict[str, Any]:
    """Load scenario from legacy single-file format."""
    with open(scenario_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Get request - either inline or from file reference
    request = data.get("request")
    if request is None:
        request_file = data.get("request_file")
        if request_file:
            # Resolve relative to repo root (parent of scenarios_root)
            repo_root = scenarios_root.parent
            request_path = repo_root / request_file
            if request_path.exists():
                with open(request_path, "r", encoding="utf-8") as f:
                    request = json.load(f)
            else:
                raise FileNotFoundError(f"Request file not found: {request_file}")
        else:
            raise ValueError(f"Scenario missing 'request' or 'request_file': {scenario_file}")

    return {
        "request": request,
        "expected_kpis": data.get("expected_kpis", {}),
        "tolerances": data.get("tolerances", {}),
    }


def run_validate_pack(
    pack_name: str,
    validate_one_fn: Callable[[Dict, Dict, Dict], Dict[str, Any]],
    scenarios_root: Optional[Path] = None,
    packs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run validation for a complete scenario pack.

    Args:
        pack_name: Name of the pack to validate
        validate_one_fn: Function to validate one scenario.
            Signature: (request, expected_kpis, tolerances) -> result_dict
            Result should contain: passed, diffs, run_id, request_hash
        scenarios_root: Root directory for scenarios
        packs_dir: Directory containing pack YAML files

    Returns:
        Dict with pack result:
        {
            "pack": "baseline",
            "pass": false,
            "summary": {"total": 11, "pass": 10, "fail": 1},
            "scenarios": [
                {
                    "name": "scenario_name",
                    "pass": false,
                    "mismatch_count": 2,
                    "run_id": "...",
                    "request_hash": "...",
                    "top_mismatches": [...]
                }
            ]
        }
    """
    scenarios_root = scenarios_root or SCENARIOS_ROOT
    packs_dir = packs_dir or PACKS_DIR

    # Load pack
    try:
        scenario_names = load_pack(pack_name, packs_dir)
    except Exception as e:
        return {
            "pack": pack_name,
            "pass": False,
            "summary": {"total": 0, "pass": 0, "fail": 0, "error": 1},
            "scenarios": [],
            "error": str(e),
        }

    # Run each scenario
    results: List[ScenarioResult] = []
    pass_count = 0
    fail_count = 0
    error_count = 0

    for scenario_name in scenario_names:
        try:
            # Load scenario files
            scenario_data = load_scenario_files(scenario_name, scenarios_root)

            # Run validation
            result = validate_one_fn(
                scenario_data["request"],
                scenario_data["expected_kpis"],
                scenario_data["tolerances"],
            )

            # Extract results
            passed = result.get("passed", result.get("pass", False))
            diffs = result.get("diffs", [])
            run_id = result.get("run_id")
            request_hash = result.get("request_hash")
            ledger_diffs = result.get("ledger_diffs", [])  # v1.9.0

            # Count mismatches (failed diffs)
            mismatches = [d for d in diffs if not d.get("pass", True)]
            mismatch_count = len(mismatches)

            # Get top 5 mismatches by absolute difference
            top_mismatches = _get_top_mismatches(mismatches, max_count=5)

            if passed:
                pass_count += 1
            else:
                fail_count += 1

            results.append(ScenarioResult(
                name=scenario_name,
                passed=passed,
                mismatch_count=mismatch_count,
                run_id=run_id,
                request_hash=request_hash,
                top_mismatches=top_mismatches,
                ledger_diffs=ledger_diffs,  # v1.9.0
            ))

        except Exception as e:
            logger.error(f"Error validating scenario {scenario_name}: {e}")
            error_count += 1
            fail_count += 1
            results.append(ScenarioResult(
                name=scenario_name,
                passed=False,
                error=str(e),
            ))

    all_passed = fail_count == 0 and error_count == 0

    return {
        "pack": pack_name,
        "pass": all_passed,
        "summary": {
            "total": len(scenario_names),
            "pass": pass_count,
            "fail": fail_count,
            "error": error_count,
        },
        "scenarios": [_scenario_result_to_dict(r) for r in results],
    }


def _get_top_mismatches(mismatches: List[Dict], max_count: int = 5) -> List[Dict]:
    """Get top N mismatches sorted by absolute difference."""
    # Sort by absolute difference (descending)
    sorted_mismatches = sorted(
        mismatches,
        key=lambda d: abs(d.get("abs_diff", 0)),
        reverse=True,
    )

    # Take top N and extract relevant fields
    top = []
    for m in sorted_mismatches[:max_count]:
        top.append({
            "field": m.get("field", "unknown"),
            "expected": m.get("expected"),
            "actual": m.get("actual"),
            "abs_diff": m.get("abs_diff"),
            "rel_diff": m.get("rel_diff"),
        })

    return top


def compute_ledger_diffs(
    expected_ledger: Optional[Dict[str, Any]],
    actual_ledger: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compute category-level diffs between expected and actual money ledger (v1.9.0).

    Args:
        expected_ledger: Expected money_ledger from scenario expected_kpis
        actual_ledger: Actual money_ledger from sizing response

    Returns:
        List of ledger category diffs with baseline/project/delta values
    """
    if not expected_ledger or not actual_ledger:
        return []

    # Cost categories to compare
    categories = [
        "import_energy_cost_pln",
        "export_revenue_pln",
        "other_fees_pln",
        "capacity_fee_pln",
        "demand_charge_pln",
        "unserved_penalty_pln",
        "degradation_cost_pln",
        "total_cost_pln",
    ]

    diffs = []

    for category in categories:
        # Get expected values
        expected_baseline = expected_ledger.get("baseline_annual", {}).get(category, 0)
        expected_project = expected_ledger.get("project_annual", {}).get(category, 0)
        expected_delta = expected_ledger.get("delta_annual_pln", {}).get(category, 0)

        # Get actual values
        actual_baseline = actual_ledger.get("baseline_annual", {}).get(category, 0)
        actual_project = actual_ledger.get("project_annual", {}).get(category, 0)
        actual_delta = actual_ledger.get("delta_annual_pln", {}).get(category, 0)

        # Calculate diff (expected - actual)
        diff_pln = expected_delta - actual_delta

        # Only include if there's a meaningful difference (> 0.01 PLN)
        if abs(diff_pln) > 0.01:
            diffs.append({
                "category": category,
                "baseline_expected": expected_baseline,
                "baseline_actual": actual_baseline,
                "project_expected": expected_project,
                "project_actual": actual_project,
                "delta_expected": expected_delta,
                "delta_actual": actual_delta,
                "diff_pln": diff_pln,
            })

    # Sort by absolute diff (largest first)
    diffs.sort(key=lambda d: abs(d.get("diff_pln", 0)), reverse=True)

    return diffs


def _scenario_result_to_dict(result: ScenarioResult) -> Dict[str, Any]:
    """Convert ScenarioResult to dict for JSON serialization."""
    d = {
        "name": result.name,
        "pass": result.passed,
        "mismatch_count": result.mismatch_count,
    }

    if result.run_id:
        d["run_id"] = result.run_id
    if result.request_hash:
        d["request_hash"] = result.request_hash
    if result.top_mismatches:
        d["top_mismatches"] = result.top_mismatches
    if result.ledger_diffs:  # v1.9.0
        d["ledger_diffs"] = result.ledger_diffs
    if result.error:
        d["error"] = result.error

    return d
